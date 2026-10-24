"""
First-transfer readiness: KYC + one-time processing fee, enforced server-side.

The in-memory fake Supabase stands in for the database; the real routes, real
tokens and the real claim code run. Not covered here (needs a real Postgres or a
real Paystack webhook): see the report's "tests not run" list.
"""
import importlib
import sys
import types

import pytest
from eth_account import Account
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_amount_claims import _setup  # wallet + chain-config + reserve RPC stand-in

KYC_BODY = {"legal_name": "Ama Mensah", "country": "GH", "id_type": "passport", "id_number": "G1234567890"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", Account.create().key.hex())
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "97")
    monkeypatch.setenv("XERA_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_TOKEN_SECRET", "admin-test-secret")
    monkeypatch.delenv("XERA_ADMIN_ONCHAIN_PILOT", raising=False)
    monkeypatch.delenv("XERA_TRANSFER_FEE_AMOUNT_MINOR", raising=False)
    monkeypatch.delenv("XERA_TRANSFER_FEE_CURRENCY", raising=False)


def _mod(name):
    return importlib.import_module(name)


def _kyc(fake, uid, status="VERIFIED"):
    fake.store.setdefault("xera_kyc", []).append({"user_id": uid, "status": status, "reviewed_by": 999 if status == "VERIFIED" else None})


def _fee(fake, uid, status="PAID", amount=100, currency="USD", ref="ref-%d"):
    row = {"user_id": uid, "status": status, "amount_minor": amount, "currency": currency}
    if status == "PAID":
        row.update(payment_reference=ref % uid, paid_at="2026-10-24T00:00:00Z")
    fake.store.setdefault("xera_transfer_fee", []).append(row)


@pytest.fixture
def api(fake_supabase):
    rc, rr = _mod("xera.routes_chain"), _mod("xera.routes_readiness")
    ua, aa = _mod("xera.user_auth"), _mod("xera.admin_auth")
    app = FastAPI()
    app.include_router(rc.router, prefix="/api/xera")
    app.include_router(rr.router, prefix="/api/xera")
    app.include_router(rr.admin_router, prefix="/api/admin/xera")
    fake_supabase.store["admin_agents"] = [{"user_id": 7, "is_active": True}, {"user_id": 9, "is_active": False}]
    return types.SimpleNamespace(
        client=TestClient(app), fake=fake_supabase,
        h=lambda uid: {"Authorization": f"Bearer {ua.make_user_token(uid)}"},
        a=lambda uid: {"Authorization": f"Bearer {aa.make_admin_token(uid)}"},
    )


def _sign(api, uid, amount="10"):
    return api.client.post("/api/xera/claim/sign-amount", headers=api.h(uid), json={"chain": "BNB", "amount": amount})


# ---- gate: 3,4,5 ------------------------------------------------------------
def test_transfer_blocked_when_kyc_incomplete_and_nothing_is_reserved(api):
    _, state = _setup(api.fake, claimable=50)
    _fee(api.fake, 1)
    r = _sign(api, 1)
    assert r.status_code == 403 and r.json()["code"] == "transfer_requirements_incomplete"
    assert r.json()["missing"] == ["kyc_not_verified"] and state["reserved"] == []


def test_transfer_blocked_when_fee_unpaid(api):
    _, state = _setup(api.fake, claimable=50)
    _kyc(api.fake, 1)
    r = _sign(api, 1)
    assert r.status_code == 403 and r.json()["missing"] == ["fee_not_paid"] and state["reserved"] == []


def test_both_missing_requirements_are_reported(api):
    _setup(api.fake, claimable=50)
    r = _sign(api, 1)
    assert r.status_code == 403 and set(r.json()["missing"]) == {"kyc_not_verified", "fee_not_paid"}
    assert len(r.json()["messages"]) == 2


def test_retry_and_legacy_migration_are_gated_too(api):
    _setup(api.fake, claimable=50)
    r = api.client.post("/api/xera/claim/retry", headers=api.h(1), json={"chain": "BNB", "reference_id": "x"})
    # retry looks the claim up first; an unknown claim is a 404, but a real FAILED claim hits the gate:
    api.fake.store["xera_onchain_claims"] = [{"reference_id": "x", "user_id": 1, "chain": "BNB", "status": "FAILED"}]
    r = api.client.post("/api/xera/claim/retry", headers=api.h(1), json={"chain": "BNB", "reference_id": "x"})
    assert r.status_code == 403 and r.json()["code"] == "transfer_requirements_incomplete"

    api.fake.store["xera_migration_snapshot"] = [{"user_id": 1, "claimed": False, "merkle_proof": ["0x1"], "leaf_index": 0, "legacy_balance": 5}]
    api.fake.store["xera_chain_config"][0]["xera_migration_address"] = "0x" + "EF" * 20
    m = api.client.post("/api/xera/migration/claim/prepare", headers=api.h(1), json={"chain": "BNB"})
    assert m.status_code == 403 and m.json()["code"] == "transfer_requirements_incomplete"


# ---- gate: 6, 14 ------------------------------------------------------------
def test_verified_and_paid_still_need_a_verified_wallet(api):
    _setup(api.fake, claimable=50, wallet="manual")
    _kyc(api.fake, 1); _fee(api.fake, 1)
    r = _sign(api, 1)
    assert r.status_code == 400 and "hasn't been verified" in r.json()["detail"]


def test_ready_user_still_cannot_transfer_while_onchain_is_disabled(api):
    _setup(api.fake, claimable=50)
    api.fake.store["xera_chain_config"][0]["onchain_enabled"] = False
    _kyc(api.fake, 1); _fee(api.fake, 1)
    assert _sign(api, 1).status_code == 403 and _sign(api, 1).json()["detail"] == "On-chain claims are currently disabled."


def test_ready_user_can_transfer_and_amounts_are_untouched(api):
    _, state = _setup(api.fake, claimable=50)
    _kyc(api.fake, 1); _fee(api.fake, 1)
    r = _sign(api, 1, "40")
    assert r.status_code == 200
    p = state["reserved"][0]
    assert p["p_amount"] == "40" and p["p_transferable_amount"] == "10.00" or float(p["p_transferable_amount"]) == 10.0
    assert float(p["p_locked_amount"]) == 30.0


# ---- 7, 8, 9, 11 ------------------------------------------------------------
def test_forged_frontend_kyc_status_is_rejected_and_submit_only_reaches_pending(api):
    forged = api.client.post("/api/xera/kyc/submit", headers=api.h(1), json={**KYC_BODY, "status": "VERIFIED"})
    assert forged.status_code == 422
    assert api.fake.store.get("xera_kyc", []) == []
    ok = api.client.post("/api/xera/kyc/submit", headers=api.h(1), json=KYC_BODY)
    assert ok.status_code == 200 and ok.json()["kyc"]["status"] == "PENDING"
    assert api.client.get("/api/xera/readiness", headers=api.h(1)).json()["kyc"]["status"] == "PENDING"
    assert "kyc_not_verified" in api.client.get("/api/xera/readiness", headers=api.h(1)).json()["missing"]


def test_no_user_route_can_mark_the_fee_paid(api):
    paths = set(api.client.app.openapi()["paths"])
    assert not any("fee" in p and ("paid" in p or "confirm" in p) for p in paths)
    for body in ({"status": "PAID"}, {"fee_status": "PAID", "paid": True}):
        for path in ("/api/xera/readiness", "/api/xera/kyc/submit"):
            r = api.client.post(path, headers=api.h(1), json=body)
            assert r.status_code in (404, 405, 422)
    assert api.client.get("/api/xera/readiness", headers=api.h(1)).json()["fee"]["status"] == "UNPAID"


@pytest.mark.parametrize("row", [
    {"status": "FAILED"}, {"status": "PENDING"},
    {"status": "PAID", "amount_minor": 100, "currency": "USD"},                                    # no payment reference
    {"status": "PAID", "payment_reference": "r", "paid_at": "x", "amount_minor": 100, "currency": "GHS"},   # wrong currency
    {"status": "PAID", "payment_reference": "r", "paid_at": "x", "amount_minor": 1, "currency": "USD"},     # wrong amount
])
def test_only_a_matching_confirmed_payment_counts_as_paid(api, row):
    api.fake.store["xera_transfer_fee"] = [{"user_id": 1, **row}]
    assert api.client.get("/api/xera/readiness", headers=api.h(1)).json()["fee"]["status"] != "PAID"
    assert "fee_not_paid" in api.client.get("/api/xera/readiness", headers=api.h(1)).json()["missing"]


def test_one_users_kyc_and_payment_cannot_satisfy_another(api):
    _setup(api.fake, claimable=50, user_id=1)
    api.fake.store["xera_external_wallets"].append(
        {"user_id": 2, "chain": "BNB", "address": Account.create().address, "status": "VERIFIED", "connection_method": "wallet"})
    _kyc(api.fake, 2); _fee(api.fake, 2)
    assert _sign(api, 1).status_code == 403
    assert _sign(api, 2).status_code == 200


# ---- admin review / pilot ---------------------------------------------------
def test_kyc_review_needs_an_active_admin(api):
    api.client.post("/api/xera/kyc/submit", headers=api.h(1), json=KYC_BODY)
    body = {"decision": "VERIFIED"}
    assert api.client.post("/api/admin/xera/kyc/1/review", json=body).status_code in (401, 422)
    assert api.client.post("/api/admin/xera/kyc/1/review", headers=api.h(1), json=body).status_code == 401   # user token
    assert api.client.post("/api/admin/xera/kyc/1/review", headers=api.a(9), json=body).status_code == 403   # revoked admin
    assert api.client.get("/api/admin/xera/kyc/pending", headers=api.h(1)).status_code == 401


def test_admin_review_verifies_notifies_and_blocks_self_review(api):
    api.client.post("/api/xera/kyc/submit", headers=api.h(1), json=KYC_BODY)
    pend = api.client.get("/api/admin/xera/kyc/pending", headers=api.a(7)).json()["pending"]
    assert pend[0]["id_last4"] == "7890" and "id_number" not in pend[0]
    ok = api.client.post("/api/admin/xera/kyc/1/review", headers=api.a(7), json={"decision": "VERIFIED"})
    assert ok.status_code == 200
    r = api.client.get("/api/xera/readiness", headers=api.h(1)).json()
    assert r["kyc"]["status"] == "VERIFIED" and r["notifications"][0]["kind"] == "kyc_verified"
    assert api.fake.store["xera_admin_actions"][0]["action"] == "kyc_review"
    # a decided request can't be re-decided; an admin can't review themselves
    assert api.client.post("/api/admin/xera/kyc/1/review", headers=api.a(7), json={"decision": "FAILED", "note": "x"}).status_code == 409
    api.client.post("/api/xera/kyc/submit", headers=api.h(7), json=KYC_BODY)
    assert api.client.post("/api/admin/xera/kyc/7/review", headers=api.a(7), json={"decision": "VERIFIED"}).status_code == 403


def test_failed_review_needs_a_note_and_allows_resubmission(api):
    api.client.post("/api/xera/kyc/submit", headers=api.h(1), json=KYC_BODY)
    assert api.client.post("/api/admin/xera/kyc/1/review", headers=api.a(7), json={"decision": "FAILED"}).status_code == 400
    api.client.post("/api/admin/xera/kyc/1/review", headers=api.a(7), json={"decision": "FAILED", "note": "Name does not match"})
    r = api.client.get("/api/xera/readiness", headers=api.h(1)).json()
    assert r["kyc"]["status"] == "FAILED" and r["kyc"]["note"] == "Name does not match"
    assert api.client.post("/api/xera/kyc/submit", headers=api.h(1), json=KYC_BODY).status_code == 200


def test_id_number_is_never_stored_only_its_last_four(api):
    api.client.post("/api/xera/kyc/submit", headers=api.h(1), json={**KYC_BODY, "id_number": "GHA-7234-5678-9012-X"})
    row = api.fake.store["xera_kyc"][0]
    assert row["id_last4"] == "012X"[-4:] and "GHA" not in str(row) and "7234" not in str(row)


def test_pilot_exemption_exists_only_while_the_pilot_is_active(api, monkeypatch):
    cfg = _mod("xera.chain.config")
    rd = _mod("xera.readiness")
    assert rd.transfer_missing(7) == ["kyc_not_verified", "fee_not_paid"]
    monkeypatch.setenv("XERA_ADMIN_ONCHAIN_PILOT", "true")
    with cfg.admin_pilot_mode():
        assert rd.transfer_missing(7) == []
    assert rd.transfer_missing(7)                                  # exemption ends with the context
    monkeypatch.setenv("XERA_ADMIN_ONCHAIN_PILOT", "false")        # flag switched off on Render
    with cfg.admin_pilot_mode():
        assert rd.transfer_missing(7) == ["kyc_not_verified", "fee_not_paid"]


def test_gate_fails_closed_when_the_tables_cannot_be_read(api):
    rd = _mod("xera.readiness")
    def boom(*_a, **_k): raise RuntimeError("relation does not exist")
    api.fake.table = boom
    assert rd.transfer_missing(1) == ["kyc_not_verified", "fee_not_paid"]


def test_mining_and_balance_code_does_not_depend_on_the_gate():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "xera"
    for name in ("mining.py", "daily.py", "launch.py", "routes.py"):
        assert "readiness" not in (root / name).read_text(), f"{name} must not be gated by KYC/fee"


def test_fee_defaults_are_usd_one_dollar_and_collection_is_off(api):
    f = api.client.get("/api/xera/readiness", headers=api.h(1)).json()["fee"]
    assert (f["amount_minor"], f["currency"], f["collection_enabled"]) == (100, "USD", False)


def test_admin_queue_lists_by_status_and_accepts_more_info_alias(api):
    api.client.post("/api/xera/kyc/submit", headers=api.h(1), json=KYC_BODY)
    assert api.client.get("/api/admin/xera/kyc?status=PENDING").status_code == 401
    assert api.client.get("/api/admin/xera/kyc?status=PENDING", headers=api.h(1)).status_code == 401
    ok = api.client.get("/api/admin/xera/kyc?status=PENDING", headers=api.a(7)).json()
    assert ok["count"] == 1 and ok["items"][0]["user_id"] == 1 and "id_number" not in ok["items"][0]
    api.client.post("/api/admin/xera/kyc/1/review", headers=api.a(7), json={"decision": "INFO_REQUIRED", "note": "Send a clearer ID"})
    assert api.client.get("/api/admin/xera/kyc?status=MORE_INFO", headers=api.a(7)).json()["count"] == 1
    assert api.client.get("/api/admin/xera/kyc?status=PENDING", headers=api.a(7)).json()["count"] == 0
    assert api.client.get("/api/admin/xera/kyc?status=NOPE", headers=api.a(7)).status_code == 400


@pytest.mark.parametrize("body,expected", [
    ({"status": "MORE_INFO", "reason": "Send a clearer ID"}, "INFO_REQUIRED"),
    ({"action": "approve"}, "VERIFIED"),
    ({"decision": "Failed", "message": "Name mismatch"}, "FAILED"),
])
def test_review_accepts_the_admin_pages_field_names(api, body, expected):
    api.client.post("/api/xera/kyc/submit", headers=api.h(1), json=KYC_BODY)
    r = api.client.post("/api/admin/xera/kyc/1/review", headers=api.a(7), json=body)
    assert r.status_code == 200 and r.json()["kyc"]["status"] == expected


def test_review_with_no_decision_is_rejected(api):
    api.client.post("/api/xera/kyc/submit", headers=api.h(1), json=KYC_BODY)
    assert api.client.post("/api/admin/xera/kyc/1/review", headers=api.a(7), json={"note": "x"}).status_code == 400
