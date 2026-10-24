"""
First-transfer readiness: KYC status, the one-time fee, and the backend gate on claims.

Real user/admin tokens, real Paystack webhook HMAC; Supabase is the in-memory fake from conftest and
Paystack's HTTP API is stubbed (test mode - nothing is ever charged). The two database functions are
re-implemented in the fake with the same rules as the SQL (see supabase/migrations/20261024_*.sql);
the SQL itself needs a Postgres run (see the deployment notes).
"""
import hashlib
import hmac
import importlib
import json
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

SECRET = "sk_test_unit"


class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


@pytest.fixture
def api(fake_supabase, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN_SECRET", "admin-test-secret")
    monkeypatch.setenv("XERA_TOKEN_SECRET", "user-test-secret")
    monkeypatch.setenv("XERA_PAYSTACK_SECRET_KEY", SECRET)
    monkeypatch.setenv("XERA_FIRST_TRANSFER_GATE", "true")
    monkeypatch.setenv("XERA_FEE_COLLECTION_ENABLED", "true")
    monkeypatch.setenv("XERA_FEE_REFUND_POLICY", "Test refund policy text.")
    monkeypatch.delenv("XERA_ADMIN_ONCHAIN_PILOT", raising=False)
    for m in ("xera.readiness", "xera.routes_readiness", "xera.routes_hashrate", "xera.payments.paystack_provider"):
        sys.modules.pop(m, None)
    readiness = importlib.import_module("xera.readiness")
    rr = importlib.import_module("xera.routes_readiness")
    rc = importlib.import_module("xera.routes_chain")
    user_auth = importlib.import_module("xera.user_auth")
    admin_auth = importlib.import_module("xera.admin_auth")
    provider = importlib.import_module("xera.payments.paystack_provider")

    s = fake_supabase.store
    s["users"] = [{"id": 1, "email": "a@example.com"}, {"id": 2, "email": "b@example.com"}]
    s["admin_agents"] = [{"user_id": 7, "is_active": True}]

    # --- the two SQL functions, same rules as the migration
    def confirm(p):
        rows = [r for r in s.get("xera_fee_payments", []) if r["reference"] == p["p_reference"]]
        if not rows:
            raise RuntimeError("fee_payment_not_found")
        row = rows[0]
        if row["status"] != "PENDING":
            return types.SimpleNamespace(data=[dict(row)])
        if row["amount_minor"] != p["p_amount_minor"] or row["currency"].upper() != (p["p_currency"] or "").upper():
            raise RuntimeError("fee_amount_mismatch")
        if any(r["user_id"] == row["user_id"] and r["status"] == "PAID" for r in s["xera_fee_payments"]):
            raise RuntimeError("duplicate key value violates unique constraint uq_xera_fee_one_paid_per_user")
        row.update(status="PAID", provider_tx_id=p["p_provider_tx_id"])
        return types.SimpleNamespace(data=[dict(row)])

    def fail(p):
        rows = [r for r in s.get("xera_fee_payments", []) if r["reference"] == p["p_reference"]]
        if rows and rows[0]["status"] == "PENDING":
            rows[0]["status"] = "FAILED"
        return types.SimpleNamespace(data=[dict(rows[0])] if rows else [])
    fake_supabase.rpc_handlers["xera_confirm_fee_payment"] = confirm
    fake_supabase.rpc_handlers["xera_fail_fee_payment"] = fail

    # --- Paystack stub: what the verify API says about each reference
    paystack = {"verify": {}, "init_ok": True}

    def fake_post(url, **kw):
        if not paystack["init_ok"]:
            return _Resp({"status": False, "message": "Currency not supported by merchant"})
        return _Resp({"status": True, "data": {"authorization_url": "https://checkout.example/pay", "access_code": "x"}})
    monkeypatch.setattr(readiness.httpx, "post", fake_post)
    monkeypatch.setattr(provider.PaystackHashrateProvider, "verify",
                        lambda self, reference: paystack["verify"].get(reference, {"confirmed": False, "raw": {}}))

    app = FastAPI()
    app.include_router(rr.router, prefix="/api/xera")
    app.include_router(rr.admin_router, prefix="/api/admin/xera/kyc")
    app.include_router(rc.router, prefix="/api/xera")
    return types.SimpleNamespace(
        client=TestClient(app), fake=fake_supabase, store=s, readiness=readiness, paystack=paystack,
        monkeypatch=monkeypatch,
        user=lambda uid: {"Authorization": f"Bearer {user_auth.make_user_token(uid)}"},
        admin=lambda uid: {"Authorization": f"Bearer {admin_auth.make_admin_token(uid)}"},
    )


KYC = {"legal_name": "Ama Mensah", "country": "Ghana", "id_type": "Ghana Card", "id_last4": "1234"}


def _mark_kyc(api, uid, status):
    api.store.setdefault("xera_kyc", []).append({"user_id": uid, "status": status, "review_note": None})


def _mark_fee(api, uid, status="PAID", ref=None):
    api.store.setdefault("xera_fee_payments", []).append({
        "user_id": uid, "reference": ref or f"xera-fee-{uid}-{status}", "amount_minor": 100, "currency": "USD",
        "status": status, "created_at": "2026-10-24T10:00:00+00:00"})


def _sign(api, uid=1, **kw):
    return api.client.post("/api/xera/claim/sign-amount", json={"chain": "BNB", "amount": "5"}, headers=api.user(uid))


def _webhook(api, event, reference):
    body = json.dumps({"event": event, "data": {"reference": reference}}).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
    return body, sig


def _post_webhook(api, event, reference, sig=None):
    from fastapi import APIRouter, Header, Request
    body, good = _webhook(api, event, reference)
    # exercise the real dispatch used by routes_hashrate.py
    payload = json.loads(body)
    return api.readiness.handle_fee_webhook(body, sig or good, payload)


# ---------------------------------------------------------------- the gate (cases 3-6, 14)
def test_first_transfer_blocked_when_kyc_incomplete(api):
    _mark_fee(api, 1)
    r = _sign(api)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "first_transfer_requirements_incomplete"
    assert r.json()["detail"]["missing"] == ["kyc"]


def test_first_transfer_blocked_when_fee_unpaid(api):
    _mark_kyc(api, 1, "VERIFIED")
    r = _sign(api)
    assert r.status_code == 403 and r.json()["detail"]["missing"] == ["fee"]


def test_both_missing_requirements_are_reported(api):
    r = _sign(api)
    assert r.status_code == 403 and r.json()["detail"]["missing"] == ["kyc", "fee"]
    assert "keep mining" in r.json()["detail"]["message"]


@pytest.mark.parametrize("kyc", ["PENDING", "FAILED", "MORE_INFO"])
def test_only_verified_kyc_counts(api, kyc):
    _mark_fee(api, 1)
    _mark_kyc(api, 1, kyc)
    assert _sign(api).json()["detail"]["missing"] == ["kyc"]


@pytest.mark.parametrize("fee", ["PENDING", "FAILED"])
def test_only_paid_fee_counts(api, fee):
    _mark_kyc(api, 1, "VERIFIED")
    _mark_fee(api, 1, fee)
    assert _sign(api).json()["detail"]["missing"] == ["fee"]


def test_verified_kyc_and_paid_fee_do_not_bypass_wallet_verification(api):
    _mark_kyc(api, 1, "VERIFIED")
    _mark_fee(api, 1)
    r = _sign(api)                                   # gate passes, the existing wallet check still stops it
    assert r.status_code == 400 and "wallet" in r.json()["detail"].lower()


def test_mainnet_stays_closed_even_when_ready(api):
    _mark_kyc(api, 1, "VERIFIED")
    _mark_fee(api, 1)
    api.store["xera_chain_config"] = [{"chain": "BNB", "network": "mainnet", "xera_distributor_address": "0x" + "ab" * 20,
                                       "onchain_enabled": False}]
    api.store["xera_external_wallets"] = [{"user_id": 1, "chain": "BNB", "address": "0x" + "cd" * 20, "status": "VERIFIED"}]
    r = _sign(api)
    assert r.status_code == 403 and "disabled" in r.json()["detail"].lower()


def test_retry_and_legacy_migration_are_gated_too(api):
    r = api.client.post("/api/xera/claim/retry", json={"chain": "BNB", "reference_id": "x"}, headers=api.user(1))
    assert r.status_code == 403 and r.json()["detail"]["missing"] == ["kyc", "fee"]
    r = api.client.post("/api/xera/migration/claim/prepare", json={"chain": "BNB"}, headers=api.user(1))
    assert r.status_code == 403 and r.json()["detail"]["missing"] == ["kyc", "fee"]


def test_gate_is_enforced_without_the_frontend_and_needs_a_token(api):
    assert api.client.post("/api/xera/claim/sign-amount", json={"chain": "BNB", "amount": "5"}).status_code == 401


def test_admin_pilot_is_exempt_but_users_never_are(api):
    from xera.chain.config import admin_pilot_mode
    api.monkeypatch.setenv("XERA_ADMIN_ONCHAIN_PILOT", "true")
    api.readiness.require_first_transfer_ready.__globals__  # noqa: B018 (module is loaded)
    with admin_pilot_mode():
        api.readiness.require_first_transfer_ready(7)        # no raise inside the pilot
    with pytest.raises(api.readiness.TransferRequirementsError):
        api.readiness.require_first_transfer_ready(7)        # outside it, the same user is gated


# ---------------------------------------------------------------- KYC (7, 13)
def test_forged_frontend_kyc_status_is_ignored(api):
    r = api.client.post("/api/xera/kyc/submit", json={**KYC, "status": "VERIFIED", "verified": True}, headers=api.user(1))
    assert r.status_code == 200 and r.json()["kyc"]["status"] == "PENDING"
    assert api.store["xera_kyc"][0]["status"] == "PENDING"
    assert api.client.get("/api/xera/readiness?kyc=VERIFIED", headers=api.user(1)).json()["kyc"]["status"] == "PENDING"


def test_only_an_admin_can_verify_and_it_is_audited(api):
    api.client.post("/api/xera/kyc/submit", json=KYC, headers=api.user(1))
    body = {"decision": "VERIFIED"}
    assert api.client.post("/api/admin/xera/kyc/1/review", json=body, headers=api.user(1)).status_code == 401   # user token
    assert api.client.post("/api/admin/xera/kyc/1/review", json=body).status_code == 401
    api.store["admin_agents"][0]["is_active"] = False
    assert api.client.post("/api/admin/xera/kyc/1/review", json=body, headers=api.admin(7)).status_code == 403   # revoked
    api.store["admin_agents"][0]["is_active"] = True
    r = api.client.post("/api/admin/xera/kyc/1/review", json=body, headers=api.admin(7))
    assert r.status_code == 200 and r.json()["kyc"]["verified"] is True
    assert any(e["event"] == "KYC_VERIFIED" and e["actor_id"] == 7 for e in api.store["xera_readiness_events"])
    assert any(n["kind"] == "KYC_VERIFIED" for n in api.store["xera_notifications"])


def test_failing_needs_a_note_and_the_user_sees_it(api):
    api.client.post("/api/xera/kyc/submit", json=KYC, headers=api.user(1))
    assert api.client.post("/api/admin/xera/kyc/1/review", json={"decision": "FAILED"}, headers=api.admin(7)).status_code == 400
    api.client.post("/api/admin/xera/kyc/1/review", json={"decision": "FAILED", "note": "ID unreadable"}, headers=api.admin(7))
    kyc = api.client.get("/api/xera/readiness", headers=api.user(1)).json()["kyc"]
    assert kyc["status"] == "FAILED" and kyc["note"] == "ID unreadable"
    assert api.client.post("/api/xera/kyc/submit", json=KYC, headers=api.user(1)).json()["kyc"]["status"] == "PENDING"   # can resubmit


def test_verified_users_cannot_resubmit_and_no_full_id_is_stored(api):
    r = api.client.post("/api/xera/kyc/submit", json={**KYC, "id_last4": "GHA-123456789-0"}, headers=api.user(1))
    assert r.status_code == 200
    assert api.store["xera_kyc"][0]["id_last4"] == "89-0"          # only the last 4 characters are ever kept
    api.client.post("/api/admin/xera/kyc/1/review", json={"decision": "VERIFIED"}, headers=api.admin(7))
    assert api.client.post("/api/xera/kyc/submit", json=KYC, headers=api.user(1)).status_code == 409


def test_dashboard_shows_server_confirmed_statuses(api):
    h = api.user(1)
    o = api.client.get("/api/xera/readiness", headers=h).json()
    assert o["kyc"]["status"] == "UNVERIFIED" and o["fee"]["status"] == "UNPAID" and o["missing"] == ["kyc", "fee"]
    assert o["fee"]["amount"] == "1.00" and o["fee"]["currency"] == "USD"
    for kyc in ("PENDING", "VERIFIED", "FAILED", "MORE_INFO"):
        api.store["xera_kyc"] = [{"user_id": 1, "status": kyc, "review_note": "n"}]
        assert api.client.get("/api/xera/readiness", headers=h).json()["kyc"]["status"] == kyc
    for fee in ("PENDING", "FAILED", "PAID"):
        api.store["xera_fee_payments"] = []
        _mark_fee(api, 1, fee)
        api.store["xera_fee_payments"][0]["created_at"] = api.readiness._now().isoformat()
        assert api.client.get("/api/xera/readiness", headers=h).json()["fee"]["status"] == fee


def test_a_stale_pending_attempt_shows_unpaid_again(api):
    _mark_fee(api, 1, "PENDING")          # created hours ago
    assert api.client.get("/api/xera/readiness", headers=api.user(1)).json()["fee"]["status"] == "UNPAID"


# ---------------------------------------------------------------- fee (8-11)
def _checkout(api, uid=1):
    r = api.client.post("/api/xera/fee/checkout", headers=api.user(uid))
    assert r.status_code == 200, r.text
    return r.json()["reference"]


def test_checkout_creates_a_pending_attempt_for_the_authenticated_user_only(api):
    ref = _checkout(api)
    row = api.store["xera_fee_payments"][0]
    assert row["user_id"] == 1 and row["status"] == "PENDING" and row["amount_minor"] == 100 and row["currency"] == "USD"
    assert ref.startswith("xera-fee-")
    assert api.client.get("/api/xera/readiness", headers=api.user(1)).json()["fee"]["status"] == "PENDING"


def test_frontend_success_redirect_is_not_proof_of_payment(api):
    ref = _checkout(api)
    r = api.client.get(f"/api/xera/fee/verify?reference={ref}&status=success&trxref={ref}", headers=api.user(1))
    assert r.status_code == 200 and r.json()["fee"]["status"] == "PENDING"      # Paystack did not confirm
    assert api.store["xera_fee_payments"][0]["status"] == "PENDING"


def test_confirmed_payment_marks_paid_once_and_duplicate_webhooks_do_nothing(api):
    ref = _checkout(api)
    api.paystack["verify"][ref] = {"confirmed": True, "tx_hash": "tx1", "amount_minor": 100, "currency": "USD"}
    _post_webhook(api, "charge.success", ref)
    _post_webhook(api, "charge.success", ref)
    _post_webhook(api, "charge.success", ref)
    assert [r["status"] for r in api.store["xera_fee_payments"]] == ["PAID"]
    assert len([n for n in api.store["xera_notifications"] if n["kind"] == "FEE_PAID"]) == 1
    assert api.client.get("/api/xera/readiness", headers=api.user(1)).json()["fee"]["paid"] is True


def test_failed_payment_does_not_mark_paid(api):
    ref = _checkout(api)
    _post_webhook(api, "charge.failed", ref)
    assert api.store["xera_fee_payments"][0]["status"] == "FAILED"
    assert api.client.get("/api/xera/readiness", headers=api.user(1)).json()["fee"]["status"] == "FAILED"
    assert api.client.get("/api/xera/readiness", headers=api.user(1)).json()["missing"] == ["kyc", "fee"]


def test_webhook_needs_a_valid_signature(api):
    ref = _checkout(api)
    api.paystack["verify"][ref] = {"confirmed": True, "tx_hash": "t", "amount_minor": 100, "currency": "USD"}
    with pytest.raises(api.readiness.ReadinessError):
        _post_webhook(api, "charge.success", ref, sig="deadbeef")
    assert api.store["xera_fee_payments"][0]["status"] == "PENDING"


@pytest.mark.parametrize("amount,currency", [(100, "GHS"), (50, "USD"), (10000, "USD")])
def test_wrong_amount_or_currency_never_counts(api, amount, currency):
    ref = _checkout(api)
    api.paystack["verify"][ref] = {"confirmed": True, "tx_hash": "t", "amount_minor": amount, "currency": currency}
    with pytest.raises(api.readiness.ReadinessError):
        _post_webhook(api, "charge.success", ref)
    assert api.store["xera_fee_payments"][0]["status"] == "PENDING"


def test_one_users_payment_cannot_satisfy_another_users_requirement(api):
    ref = _checkout(api, uid=1)
    api.paystack["verify"][ref] = {"confirmed": True, "tx_hash": "t", "amount_minor": 100, "currency": "USD"}
    _post_webhook(api, "charge.success", ref)
    assert api.client.get("/api/xera/readiness", headers=api.user(2)).json()["fee"]["status"] == "UNPAID"
    assert api.client.get(f"/api/xera/fee/verify?reference={ref}", headers=api.user(2)).status_code == 404
    _mark_kyc(api, 2, "VERIFIED")
    assert _sign(api, uid=2).json()["detail"]["missing"] == ["fee"]


def test_user_return_from_checkout_verifies_with_paystack(api):
    ref = _checkout(api)
    api.paystack["verify"][ref] = {"confirmed": True, "tx_hash": "t", "amount_minor": 100, "currency": "USD"}
    r = api.client.get(f"/api/xera/fee/verify?reference={ref}", headers=api.user(1))
    assert r.json()["fee"]["status"] == "PAID"


def test_collection_off_by_default_and_paystack_refusal_never_switches_currency(api):
    api.monkeypatch.setenv("XERA_FEE_COLLECTION_ENABLED", "false")
    assert api.client.post("/api/xera/fee/checkout", headers=api.user(1)).status_code == 503
    assert api.store.get("xera_fee_payments", []) == []
    api.monkeypatch.setenv("XERA_FEE_COLLECTION_ENABLED", "true")
    api.monkeypatch.setenv("XERA_FEE_REFUND_POLICY", "")           # flag on but no refund policy written: still closed
    assert api.client.post("/api/xera/fee/checkout", headers=api.user(1)).status_code == 503
    assert api.client.get("/api/xera/readiness", headers=api.user(1)).json()["fee"]["collection_enabled"] is False
    api.monkeypatch.setenv("XERA_FEE_REFUND_POLICY", "Test refund policy text.")
    assert api.client.get("/api/xera/readiness", headers=api.user(1)).json()["fee"]["refund_policy"] == "Test refund policy text."
    api.paystack["init_ok"] = False                       # e.g. the account cannot charge USD
    r = api.client.post("/api/xera/fee/checkout", headers=api.user(1))
    assert r.status_code == 502
    assert [p["currency"] for p in api.store["xera_fee_payments"]] == ["USD"] and api.store["xera_fee_payments"][0]["status"] == "FAILED"


def test_a_second_payment_after_paid_is_refused(api):
    _mark_fee(api, 1)
    assert api.client.post("/api/xera/fee/checkout", headers=api.user(1)).status_code == 409


def test_notifications_are_real_and_per_user(api):
    api.client.post("/api/xera/kyc/submit", json=KYC, headers=api.user(1))
    mine = api.client.get("/api/xera/notifications", headers=api.user(1)).json()["notifications"]
    assert [n["kind"] for n in mine] == ["KYC_PENDING"]
    assert api.client.get("/api/xera/notifications", headers=api.user(2)).json()["notifications"] == []
    api.client.post("/api/xera/notifications/read", headers=api.user(1))
    assert api.client.get("/api/xera/notifications", headers=api.user(1)).json()["notifications"][0]["read"] is True


# ---------------------------------------------------------------- mining untouched (1, 2, 12)
def test_mining_code_does_not_depend_on_kyc_or_fee():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "xera"
    for name in ("mining.py", "daily.py", "hashrate.py", "referrals.py", "routes.py", "wallet.py", "config.py"):
        text = (root / name).read_text()
        assert "readiness" not in text and "first_transfer" not in text, f"{name} must not be gated"
