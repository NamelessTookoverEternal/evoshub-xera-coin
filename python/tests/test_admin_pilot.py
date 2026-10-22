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
