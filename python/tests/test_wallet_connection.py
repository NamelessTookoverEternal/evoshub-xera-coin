"""
HTTP-level tests for the wallet endpoints, using REAL session tokens
(make_user_token / verify_user_token) — authentication and per-user scoping
are exercised, not stubbed. Supabase is the in-memory fake from conftest.
"""
import types

import pytest
from eth_account import Account
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _install_wallet_rpcs(fake):
    table = fake.store.setdefault("xera_external_wallets", [])

    def active(user_id, chain, **extra):
        return [r for r in table if r["user_id"] == user_id and r["chain"] == chain
                and r["status"] in ("VERIFIED", "PENDING")
                and all(r.get(k) == v for k, v in extra.items())]

    def set_manual(p):
        if any(r["status"] == "VERIFIED" for r in active(p["p_user_id"], p["p_chain"])):
            raise RuntimeError("verified_wallet_exists")
        for r in active(p["p_user_id"], p["p_chain"], connection_method="manual"):
            r["status"] = "REPLACED"
        row = {"id": len(table) + 1, "user_id": p["p_user_id"], "chain": p["p_chain"], "address": p["p_address"],
               "status": "PENDING", "connection_method": "manual", "verified_at": None, "linked_at": "now"}
        table.append(row)
        return types.SimpleNamespace(data=[dict(row)])

    def remove(p):
        rows = active(p["p_user_id"], p["p_chain"])
        if not rows:
            raise RuntimeError("wallet_not_found")
        rows[0]["status"] = "REVOKED"
        return types.SimpleNamespace(data=[dict(rows[0])])

    fake.rpc_handlers["xera_set_manual_wallet"] = set_manual
    fake.rpc_handlers["xera_remove_external_wallet"] = remove
    return table


@pytest.fixture
def api(fake_supabase, monkeypatch):
    monkeypatch.setenv("XERA_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "97")
    table = _install_wallet_rpcs(fake_supabase)
    # import_module (NOT `from xera import routes_chain`): the latter reuses the
    # stale attribute on the `xera` package and would keep talking to a previous
    # test's fake database after the fixture evicted the module from sys.modules.
    import importlib
    routes_chain = importlib.import_module("xera.routes_chain")
    user_auth = importlib.import_module("xera.user_auth")
    app = FastAPI()
    app.include_router(routes_chain.router, prefix="/api/xera")
    client = TestClient(app)
    return types.SimpleNamespace(
        client=client, table=table, fake=fake_supabase,
        h=lambda uid: {"Authorization": f"Bearer {user_auth.make_user_token(uid)}"},
    )


def test_every_wallet_endpoint_requires_a_valid_session(api):
    assert api.client.get("/api/xera/wallet/linked").status_code == 401
    assert api.client.post("/api/xera/wallet/manual", json={"chain": "BNB", "address": Account.create().address}).status_code == 401
    assert api.client.delete("/api/xera/wallet/BNB").status_code == 401
    assert api.client.get("/api/xera/wallet/linked", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_manual_bnb_address_is_saved_normalised_and_marked_unverified(api):
    addr = Account.create().address
    r = api.client.post("/api/xera/wallet/manual", headers=api.h(1), json={"chain": "BNB", "address": addr.lower()})
    assert r.status_code == 200
    body = r.json()
    assert body["wallet"]["address"] == addr                      # checksummed on the way in
    assert body["wallet"]["connection_method"] == "manual"
    assert body["wallet"]["verified"] is False
    assert "not been cryptographically verified" in body["notice"]

    listed = api.client.get("/api/xera/wallet/linked", headers=api.h(1)).json()["wallets"]
    assert [(w["chain"], w["connection_method"], w["verified"]) for w in listed] == [("BNB", "manual", False)]


def test_manual_address_validation_errors_are_precise_and_never_reach_the_database(api):
    def _boom(_params):
        raise AssertionError("database RPC must not be called for an invalid address")
    api.fake.rpc_handlers["xera_set_manual_wallet"] = _boom
    for chain, bad, expect in [
        ("BNB", "0x1234", "valid BNB wallet address"),
        ("BNB", "0x" + "0" * 40, "can't be used"),
        ("BNB", "", "enter a wallet address"),
        ("TON", "hello", "valid TON wallet address"),
        ("BNB", "test test test test test test test test test test test junk", "valid BNB wallet address"),
    ]:
        r = api.client.post("/api/xera/wallet/manual", headers=api.h(1), json={"chain": chain, "address": bad})
        assert r.status_code == 400, (chain, bad)
        assert expect in r.json()["detail"]
        assert bad == "" or bad not in r.json()["detail"]         # never echo the input back
    assert api.table == []


def test_manual_ton_address_is_stored_in_canonical_raw_form_with_friendly_display(api):
    raw = "0:" + "ab" * 32
    r = api.client.post("/api/xera/wallet/manual", headers=api.h(1), json={"chain": "TON", "address": raw})
    w = r.json()["wallet"]
    assert w["address"] == raw and w["display_address"].startswith("UQ") and w["verified"] is False


def test_users_only_ever_see_and_modify_their_own_wallets(api):
    a1, a2 = Account.create().address, Account.create().address
    api.client.post("/api/xera/wallet/manual", headers=api.h(1), json={"chain": "BNB", "address": a1})
    api.client.post("/api/xera/wallet/manual", headers=api.h(2), json={"chain": "BNB", "address": a2})

    assert [w["address"] for w in api.client.get("/api/xera/wallet/linked", headers=api.h(1)).json()["wallets"]] == [a1]
    assert [w["address"] for w in api.client.get("/api/xera/wallet/linked", headers=api.h(2)).json()["wallets"]] == [a2]

    # user 1 removes THEIR wallet; user 2's is untouched
    assert api.client.delete("/api/xera/wallet/BNB", headers=api.h(1)).status_code == 200
    assert api.client.get("/api/xera/wallet/linked", headers=api.h(1)).json()["wallets"] == []
    assert [w["address"] for w in api.client.get("/api/xera/wallet/linked", headers=api.h(2)).json()["wallets"]] == [a2]

    # removing again -> clear 404, and there is no way to name another user's row
    assert api.client.delete("/api/xera/wallet/BNB", headers=api.h(1)).status_code == 404


def test_cannot_overwrite_a_verified_wallet_with_a_manual_address(api):
    api.table.append({"id": 1, "user_id": 1, "chain": "BNB", "address": Account.create().address,
                      "status": "VERIFIED", "connection_method": "wallet", "verified_at": "t", "linked_at": "t"})
    r = api.client.post("/api/xera/wallet/manual", headers=api.h(1),
                        json={"chain": "BNB", "address": Account.create().address})
    assert r.status_code == 409 and "Disconnect it first" in r.json()["detail"]


def test_connected_wallet_is_reported_verified(api):
    addr = Account.create().address
    api.table.append({"user_id": 1, "chain": "BNB", "address": addr, "status": "VERIFIED",
                      "connection_method": "wallet", "verified_at": "t", "linked_at": "t"})
    w = api.client.get("/api/xera/wallet/linked", headers=api.h(1)).json()["wallets"][0]
    assert (w["connection_method"], w["verified"]) == ("wallet", True)


def test_chain_config_is_public_and_exposes_no_secrets(api, monkeypatch):
    monkeypatch.setenv("XERA_BNB_RPC_URL", "https://private-rpc.example/KEY123")
    monkeypatch.setenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", "0x" + "11" * 32)
    r = api.client.get("/api/xera/chain/config")
    assert r.status_code == 200
    bnb = r.json()["bnb"]
    assert bnb["chain_id"] == 97 and bnb["chain_id_hex"] == "0x61" and bnb["is_testnet"] is True
    text = r.text
    assert "KEY123" not in text and "private-rpc" not in text and "1111111111" not in text

    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "56")
    assert api.client.get("/api/xera/chain/config").json()["bnb"]["chain_id"] == 56
