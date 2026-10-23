"""
Admin on-chain pilot (routes_admin_chain.py): admins link their OWN wallets and
try a real claim before on-chain claiming is open to users.

Real admin / user tokens are used; Supabase is the in-memory fake from conftest.
The cryptography and the claim RPCs are not re-tested here (see test_claims.py,
test_wallet_connection.py); these tests pin the access rules around them.
"""
import importlib
import sys
import types

import pytest
from eth_account import Account
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def api(fake_supabase, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN_SECRET", "admin-test-secret")
    monkeypatch.setenv("XERA_TOKEN_SECRET", "user-test-secret")
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "97")
    monkeypatch.delenv("XERA_ADMIN_ONCHAIN_PILOT", raising=False)
    sys.modules.pop("xera.routes_admin_chain", None)
    mod = importlib.import_module("xera.routes_admin_chain")
    cfg = importlib.import_module("xera.chain.config")
    admin_auth = importlib.import_module("xera.admin_auth")
    user_auth = importlib.import_module("xera.user_auth")

    fake_supabase.store["admin_agents"] = [
        {"user_id": 7, "is_active": True},
        {"user_id": 9, "is_active": False},   # revoked
    ]
    table = fake_supabase.store.setdefault("xera_external_wallets", [])

    def set_manual(p):
        row = {"id": len(table) + 1, "user_id": p["p_user_id"], "chain": p["p_chain"], "address": p["p_address"],
               "status": "PENDING", "connection_method": "manual", "verified_at": None, "linked_at": "now"}
        table.append(row)
        return types.SimpleNamespace(data=[dict(row)])
    fake_supabase.rpc_handlers["xera_set_manual_wallet"] = set_manual

    app = FastAPI()
    app.include_router(mod.router, prefix="/api/admin/xera/pilot")
    return types.SimpleNamespace(
        client=TestClient(app), fake=fake_supabase, mod=mod, cfg=cfg, table=table,
        admin=lambda uid: {"Authorization": f"Bearer {admin_auth.make_admin_token(uid)}"},
        user=lambda uid: {"Authorization": f"Bearer {user_auth.make_user_token(uid)}"},
        monkeypatch=monkeypatch,
    )


P = "/api/admin/xera/pilot"
ENDPOINTS = [
    ("get", "/status", None), ("get", "/chain/config", None), ("get", "/wallet/linked", None),
    ("get", "/claim/overview", None), ("get", "/onchain/status", None),
    ("post", "/wallet/manual", {"chain": "BNB", "address": "0x" + "1" * 40}),
    ("post", "/claim/sign-amount", {"chain": "BNB", "amount": "1"}),
    ("post", "/claim/retry", {"chain": "BNB", "reference_id": "r"}),
    ("post", "/claim/confirm", {"reference_id": "r", "transaction_hash": "0x1"}),
    ("delete", "/wallet/BNB", None),
]


def _call(api, method, path, headers=None, body=None):
    return getattr(api.client, method)(P + path, headers=headers or {}, **({"json": body} if body is not None else {}))


def test_every_route_rejects_missing_garbage_and_user_tokens(api):
    for method, path, body in ENDPOINTS:
        assert _call(api, method, path, None, body).status_code == 401, path
        assert _call(api, method, path, {"Authorization": "Bearer garbage"}, body).status_code == 401, path
        # A normal XERA user token is not an admin token.
        assert _call(api, method, path, api.user(7), body).status_code == 401, path


def test_revoked_admin_is_locked_out_immediately(api):
    for method, path, body in ENDPOINTS:
        assert _call(api, method, path, api.admin(9), body).status_code == 403, path
    # ...and so is an admin token whose admin_agents row no longer exists.
    assert _call(api, "get", "/wallet/linked", api.admin(404)).status_code == 403


def test_admin_only_sees_and_changes_their_own_wallet(api):
    mine = Account.create().address
    other = Account.create().address
    api.table.append({"id": 50, "user_id": 8, "chain": "BNB", "address": other, "status": "VERIFIED",
                      "connection_method": "walletconnect", "verified_at": "now", "linked_at": "now"})
    r = _call(api, "post", "/wallet/manual", api.admin(7), {"chain": "BNB", "address": mine, "user_id": 8})
    assert r.status_code == 200
    assert {w["user_id"] for w in api.table if w["address"] == mine} == {7}     # body user_id ignored
    wallets = _call(api, "get", "/wallet/linked", api.admin(7)).json()["wallets"]
    assert [w["address"] for w in wallets] == [mine]


def test_claim_signing_is_closed_unless_pilot_flag_is_on(api):
    called = []
    api.monkeypatch.setattr(api.mod, "sign_amount_claim", lambda *a: called.append(a) or {"reference_id": "x"})
    r = _call(api, "post", "/claim/sign-amount", api.admin(7), {"chain": "BNB", "amount": "5"})
    assert r.status_code == 403 and called == []
    r = _call(api, "post", "/claim/retry", api.admin(7), {"chain": "BNB", "reference_id": "r"})
    assert r.status_code == 403


def test_claim_runs_as_the_token_admin_inside_pilot_mode(api):
    api.monkeypatch.setenv("XERA_ADMIN_ONCHAIN_PILOT", "true")
    seen = {}

    def fake_sign(user_id, chain, amount):
        seen.update(user_id=user_id, chain=chain, amount=amount, pilot=api.cfg._admin_pilot.get())
        return {"reference_id": "ref-1", "signature": "0xSECRET"}

    api.monkeypatch.setattr(api.mod, "sign_amount_claim", fake_sign)
    r = _call(api, "post", "/claim/sign-amount", api.admin(7), {"chain": "BNB", "amount": "5", "user_id": 8})
    assert r.status_code == 200
    assert seen == {"user_id": 7, "chain": "BNB", "amount": "5", "pilot": True}
    assert api.cfg._admin_pilot.get() is False                    # mode never leaks out of the request


def test_pilot_mode_only_bypasses_the_user_switch_not_the_contract_address(api):
    cfg_rows = api.fake.store.setdefault("xera_chain_config", [])
    cfg_rows.append({"chain": "BNB", "onchain_enabled": False, "xera_distributor_address": "0xabc"})
    cfg_rows.append({"chain": "TON", "onchain_enabled": False, "xera_distributor_address": None})
    api.monkeypatch.setenv("XERA_ADMIN_ONCHAIN_PILOT", "true")

    with pytest.raises(api.cfg.ChainConfigError, match="onchain_disabled"):
        api.cfg.require_onchain_enabled("BNB")                    # ordinary (user) path stays closed
    with api.cfg.admin_pilot_mode():
        assert api.cfg.require_onchain_enabled("BNB")["xera_distributor_address"] == "0xabc"
        with pytest.raises(api.cfg.ChainConfigError, match="distributor_not_configured"):
            api.cfg.require_onchain_enabled("TON")                # still needs a real contract
    with pytest.raises(api.cfg.ChainConfigError, match="onchain_disabled"):
        api.cfg.require_onchain_enabled("BNB")

    api.monkeypatch.setenv("XERA_ADMIN_ONCHAIN_PILOT", "false")
    with api.cfg.admin_pilot_mode():                              # flag off: mode does nothing
        with pytest.raises(api.cfg.ChainConfigError, match="onchain_disabled"):
            api.cfg.require_onchain_enabled("BNB")


def test_audit_rows_are_written_without_signatures_or_proofs(api):
    api.monkeypatch.setenv("XERA_ADMIN_ONCHAIN_PILOT", "true")
    api.monkeypatch.setattr(api.mod, "sign_amount_claim",
                            lambda *a: {"reference_id": "ref-1", "signature": "0xSECRET", "nonce": "n"})
    api.monkeypatch.setattr(api.mod, "verify_and_link", lambda *a, **k: {"address": "0xabc", "chain": "BNB"})
    _call(api, "post", "/claim/sign-amount", api.admin(7), {"chain": "BNB", "amount": "5"})
    _call(api, "post", "/wallet/link/verify", api.admin(7),
          {"chain": "BNB", "address": "0x" + "a" * 40, "nonce": "n1", "signature": "0xSIGSECRET"})
    rows = api.fake.store["xera_admin_actions"]
    assert {r["action"] for r in rows} == {"ADMIN_PILOT_CLAIM_SIGNED", "ADMIN_PILOT_WALLET_LINKED"}
    assert all(r["admin_id"] == 7 for r in rows)
    assert "SECRET" not in repr(rows) and "n1" not in repr(rows)


def test_status_reports_pilot_flag_and_chain_readiness(api):
    api.fake.store.setdefault("xera_chain_config", []).extend([
        {"chain": "BNB", "onchain_enabled": False, "xera_distributor_address": "0xabc"},
        {"chain": "TON", "onchain_enabled": False, "xera_distributor_address": None},
    ])
    body = _call(api, "get", "/status", api.admin(7)).json()
    assert body["pilot_enabled"] is False and body["admin_id"] == 7
    assert body["chains"]["BNB"] == {"distributor_configured": True, "user_claims_open": False}
    assert body["chains"]["TON"]["distributor_configured"] is False


# ============================================================ relayer (automatic sending)

CLAIM = {"chain": "BNB", "reference_id": "claim-1", "contract_address": "0x" + "d" * 40, "chain_id": 97,
         "user": "0x" + "a" * 40, "amount_wei": str(4 * 10**18), "reference_id_hash": "0x" + "11" * 32,
         "deadline": 9999999999, "signature": "0x" + "22" * 65}


def _relay_env(api, mp=None, **patch):
    """Pilot on, relayer 'configured', claim signing + chain calls stubbed."""
    mp = mp or api.monkeypatch
    mp.setenv("XERA_ADMIN_ONCHAIN_PILOT", "true")
    r = api.mod.relayer
    mp.setattr(r, "relayer_address", lambda: "0xRELAYER")
    calls = {"sign": [], "submit": [], "audit_failed": []}
    mp.setattr(api.mod, "sign_amount_claim", lambda uid, chain, amt: calls["sign"].append((uid, chain, amt)) or dict(CLAIM))
    mp.setattr(api.mod, "retry_claim", lambda uid, ref, chain: calls["sign"].append((uid, chain, ref)) or dict(CLAIM))
    mp.setattr(r, "submit_bnb_claim", patch.get("submit") or (lambda c: calls["submit"].append(c) or "0xabc123"))
    mp.setattr(r, "wait_for_receipt", patch.get("wait") or (lambda h, timeout_seconds=45: True))
    mp.setattr(api.mod, "confirm_claim", patch.get("confirm") or (lambda uid, ref, h: {"reference_id": ref, "status": "CONFIRMED"}))
    api.fake.rpc_handlers["xera_mark_onchain_claim_failed"] = lambda p: calls["audit_failed"].append(p["p_reference_id"]) or {}
    return calls


def test_relay_requires_admin_token_and_pilot_flag(api):
    body = {"chain": "BNB", "amount": "4"}
    assert _call(api, "post", "/claim/relay", None, body).status_code == 401
    assert _call(api, "post", "/claim/relay", api.user(7), body).status_code == 401
    assert _call(api, "post", "/claim/relay", api.admin(9), body).status_code == 403    # revoked
    assert _call(api, "post", "/claim/relay", api.admin(7), body).status_code == 403    # pilot flag off


def test_relay_signs_for_the_token_admin_sends_and_confirms(api):
    calls = _relay_env(api)
    r = _call(api, "post", "/claim/relay", api.admin(7), {"chain": "BNB", "amount": "4", "user_id": 8})
    assert r.status_code == 200
    j = r.json()
    assert j["confirmed"] is True and j["transaction_hash"] == "0xabc123"
    assert calls["sign"] == [(7, "BNB", "4")]                       # body user_id ignored
    assert calls["submit"][0]["user"] == CLAIM["user"]               # tokens go to the claim's own wallet
    actions = [x["action"] for x in api.fake.store["xera_admin_actions"]]
    assert "ADMIN_PILOT_CLAIM_RELAYED" in actions and "ADMIN_PILOT_CLAIM_CONFIRMED" in actions
    assert "0x2222" not in repr(api.fake.store["xera_admin_actions"])   # no signature in the audit log


def test_relay_needs_exactly_one_of_amount_or_reference(api):
    _relay_env(api)
    assert _call(api, "post", "/claim/relay", api.admin(7), {"chain": "BNB"}).status_code == 400
    assert _call(api, "post", "/claim/relay", api.admin(7),
                 {"chain": "BNB", "amount": "1", "reference_id": "x"}).status_code == 400
    assert _call(api, "post", "/claim/relay", api.admin(7), {"chain": "TON", "amount": "1"}).status_code == 422


def test_relay_without_gas_wallet_fails_before_reserving_anything(api):
    calls = _relay_env(api)
    def missing(): raise api.mod.relayer.RelayerError("relayer_not_configured")
    api.monkeypatch.setattr(api.mod.relayer, "relayer_address", missing)
    r = _call(api, "post", "/claim/relay", api.admin(7), {"chain": "BNB", "amount": "4"})
    assert r.status_code == 503 and calls["sign"] == []


def test_relay_refusal_releases_the_reservation(api):
    def refuse(c): raise api.mod.relayer.RelayerError("claim_would_revert")
    calls = _relay_env(api, submit=refuse)
    r = _call(api, "post", "/claim/relay", api.admin(7), {"chain": "BNB", "amount": "4"})
    assert r.status_code == 409 and "nothing was sent" in r.json()["detail"]
    assert calls["audit_failed"] == ["claim-1"]                      # marked failed so "Try again" works


def test_relay_reports_unconfirmed_when_receipt_is_slow(api):
    _relay_env(api, wait=lambda h, timeout_seconds=45: False)
    j = _call(api, "post", "/claim/relay", api.admin(7), {"chain": "BNB", "amount": "4"}).json()
    assert j["confirmed"] is False and j["transaction_hash"] == "0xabc123" and j["claim"] is None


def test_relay_retry_of_a_held_claim_uses_the_reference(api):
    calls = _relay_env(api)
    r = _call(api, "post", "/claim/relay", api.admin(7), {"chain": "BNB", "reference_id": "claim-1"})
    assert r.status_code == 200 and calls["sign"] == [(7, "BNB", "claim-1")]


# ---- relayer module itself (no network: web3 is faked)

class _FakeFn:
    def __init__(self, gas=100000, boom=False): self.gas, self.boom = gas, boom
    def estimate_gas(self, tx):
        if self.boom: raise RuntimeError("execution reverted")
        return self.gas
    def build_transaction(self, p):
        from eth_utils import to_checksum_address
        return dict(p, to=to_checksum_address("0x" + "d" * 40), value=0, data="0x")


class _FakeEth:
    def __init__(self, fn, chain_id=97, price=10**9, balance=10**18):
        self.fn, self.chain_id, self.gas_price, self._bal, self.sent = fn, chain_id, price, balance, []
        self.contract = lambda **kw: types.SimpleNamespace(functions=types.SimpleNamespace(claim=lambda *a: self.fn))
    def get_balance(self, a): return self._bal
    def get_transaction_count(self, a, b): return 0
    def send_raw_transaction(self, raw): self.sent.append(raw); return bytes.fromhex("ab" * 32)


@pytest.fixture
def rl(api, monkeypatch):
    from eth_account import Account
    key = Account.create().key.hex()
    monkeypatch.setenv("XERA_RELAYER_PRIVATE_KEY", key)
    monkeypatch.delenv("XERA_RELAYER_USE_SIGNER", raising=False)
    r = importlib.import_module("xera.chain.relayer")

    def install(**kw):
        eth = _FakeEth(kw.pop("fn", _FakeFn()), **kw)
        monkeypatch.setattr(r, "_web3", lambda: types.SimpleNamespace(eth=eth))
        monkeypatch.setattr(r.Account, "from_key", staticmethod(lambda k, _o=r.Account.from_key: _o(k)))
        return eth
    return types.SimpleNamespace(r=r, install=install, mp=monkeypatch, key=key)


def test_relayer_sends_after_simulating(rl):
    eth = rl.install()
    h = rl.r.submit_bnb_claim(dict(CLAIM))
    assert h == "0x" + "ab" * 32 and len(eth.sent) == 1


@pytest.mark.parametrize("kwargs,code", [
    ({"fn": _FakeFn(boom=True)}, "claim_would_revert"),
    ({"balance": 0}, "relayer_unfunded"),
    ({"price": 500 * 10**9}, "gas_price_too_high"),
    ({"chain_id": 56}, "wrong_network"),
])
def test_relayer_refuses_without_sending(rl, kwargs, code):
    eth = rl.install(**kwargs)
    with pytest.raises(rl.r.RelayerError, match=code):
        rl.r.submit_bnb_claim(dict(CLAIM))
    assert eth.sent == []


def test_relayer_key_rules(rl):
    rl.mp.delenv("XERA_RELAYER_PRIVATE_KEY")
    with pytest.raises(rl.r.RelayerError):
        rl.r.relayer_address()                                         # nothing configured
    rl.mp.setenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", rl.key)
    with pytest.raises(rl.r.RelayerError):
        rl.r.relayer_address()                                         # signer is NOT reused unless opted in
    rl.mp.setenv("XERA_RELAYER_USE_SIGNER", "true")
    rl.mp.setenv("XERA_BNB_CHAIN_ID", "97")
    assert rl.r.relayer_address().startswith("0x")                     # testnet + opt-in
    rl.mp.setenv("XERA_BNB_CHAIN_ID", "56")
    with pytest.raises(rl.r.RelayerError):
        rl.r.relayer_address()                                         # never on mainnet
