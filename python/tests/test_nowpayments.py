"""
USDT (BEP-20) payments through NOWPayments: hashrate purchases and the one-time fee.

The real provider code runs; only the HTTP layer (httpx) is stubbed, so request
bodies, signature checking and the verify-before-credit rules are exercised for
real. The confirm RPC stand-in below mirrors the CRYPTO branch of
supabase/migrations/20261025_xera_crypto_payments_v1.sql (stored-charge comparison).
Not covered (needs real Postgres / the live NOWPayments sandbox): see the report.
"""
import hashlib
import hmac
import json
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_hashrate import _seed_tier, hr  # noqa: F401  (hr is a fixture)

IPN_SECRET = "ipn-test-secret"
API_KEY = "np-test-key"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("NOWPAYMENTS_API_KEY", API_KEY)
    monkeypatch.setenv("NOWPAYMENTS_IPN_SECRET", IPN_SECRET)
    monkeypatch.setenv("XERA_HASHRATE_CRYPTO_ENABLED", "true")
    monkeypatch.setenv("XERA_NOWPAYMENTS_IPN_URL", "https://api.example.test/api/xera/hashrate/webhooks/nowpayments")
    monkeypatch.setenv("XERA_CRYPTO_GHS_PER_USD", "15")        # fixed rate: 15 GHS = 1 USD
    monkeypatch.setenv("XERA_CRYPTO_SUCCESS_URL", "https://evoshub.example/xera/?pay=crypto")
    monkeypatch.setenv("XERA_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("XERA_FEE_COLLECTION_ENABLED", "true")
    monkeypatch.delenv("XERA_TRANSFER_FEE_AMOUNT_MINOR", raising=False)
    monkeypatch.delenv("XERA_TRANSFER_FEE_CURRENCY", raising=False)
    monkeypatch.delenv("XERA_ADMIN_ONCHAIN_PILOT", raising=False)


class FakeNowPayments:
    """Stands in for httpx inside the provider module."""

    def __init__(self):
        self.posts, self.gets = [], []
        self.payments = {}          # payment_id -> payment dict returned by GET /payment/{id}
        self.invoice_status = 200

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append({"url": url, "headers": headers, "json": json})
        return types.SimpleNamespace(
            status_code=self.invoice_status,
            json=lambda: {"id": "inv-1", "invoice_url": "https://nowpayments.test/invoice/inv-1"} if self.invoice_status == 200 else {"message": "bad"},
        )

    def get(self, url, headers=None, timeout=None):
        self.gets.append({"url": url, "headers": headers})
        pid = url.rsplit("/", 1)[-1]
        if pid not in self.payments:
            return types.SimpleNamespace(status_code=404, json=lambda: {"message": "not found"})
        return types.SimpleNamespace(status_code=200, json=lambda: self.payments[pid])


@pytest.fixture
def np_http(monkeypatch):
    import xera.payments.nowpayments_provider as np
    fake = FakeNowPayments()
    monkeypatch.setattr(np.httpx, "post", fake.post)
    monkeypatch.setattr(np.httpx, "get", fake.get)
    return fake


@pytest.fixture
def crypto_hr(hr, fake_supabase):
    """hashrate module whose CRYPTO confirm enforces the stored charge, like the SQL does."""
    original = fake_supabase.rpc_handlers["xera_confirm_hashrate_payment"]

    def confirm(params):
        payment = next((p for p in fake_supabase.store.get("xera_hashrate_payments", [])
                        if p["reference"] == params["p_reference"]), None)
        if payment and payment["status"] in ("PENDING", "EXPIRED") and payment["provider"] == "CRYPTO":
            if (payment.get("charge_amount_minor") is None or params.get("p_verified_amount_minor") != payment["charge_amount_minor"]
                    or (params.get("p_verified_currency") or "").upper() != (payment.get("charge_currency") or "").upper()
                    or params.get("p_tx_hash") is None):
                raise RuntimeError("payment_verification_failed")
        return original(params)

    fake_supabase.rpc_handlers["xera_confirm_hashrate_payment"] = confirm
    # real CRYPTO provider (httpx stubbed per test); only Paystack is faked by the hr fixture
    from xera.payments.crypto_provider import CryptoHashrateProvider
    hr._PROVIDERS["CRYPTO"] = CryptoHashrateProvider()
    return hr


def _finished(reference, payment_id="777", price=10.0, currency="usd", pay_currency="usdtbsc", status="finished"):
    return {"payment_id": payment_id, "payment_status": status, "order_id": reference,
            "price_amount": price, "price_currency": currency, "pay_currency": pay_currency,
            "actually_paid": price, "pay_amount": price}


def _buy(crypto_hr, fake_supabase, np_http, price=150):
    _seed_tier(fake_supabase, tier_id=1, price=price, currency="GHS", daily_rate=5, duration_days=30)
    res = crypto_hr.purchase(user_id=1, tier_id=1, payment_method="CRYPTO")
    return res, res["reference"]


def _sign(body: dict, secret=IPN_SECRET) -> tuple[bytes, str]:
    raw = json.dumps(body).encode()
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return raw, hmac.new(secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()


# ------------------------------------------------------------ signature

def test_ipn_signature_accepts_valid_and_rejects_everything_else():
    import xera.payments.nowpayments_provider as np
    body = {"payment_status": "finished", "order_id": "xera-hr-1", "nested": {"b": 1, "a": 2}, "payment_id": 5}
    raw, sig = _sign(body)
    assert np.verify_ipn_signature(raw, sig) is True                       # key order in the raw body is irrelevant
    assert np.verify_ipn_signature(raw, sig.upper()) is True
    assert np.verify_ipn_signature(raw, "") is False
    assert np.verify_ipn_signature(raw, "0" * 128) is False
    tampered = json.dumps({**body, "payment_status": "finished", "payment_id": 6}).encode()
    assert np.verify_ipn_signature(tampered, sig) is False
    assert np.verify_ipn_signature(b"not json", sig) is False
    _, other = _sign(body, secret="wrong-secret")
    assert np.verify_ipn_signature(raw, other) is False


# ------------------------------------------------------------ pricing

def test_to_charge_converts_ghs_at_fixed_rate_and_rounds_up(monkeypatch):
    import xera.payments.nowpayments_provider as np
    assert np.to_charge(150, "GHS") == (1000, "USD")
    assert np.to_charge("100.00", "GHS") == (667, "USD")        # 6.666… -> 6.67, never under-charged
    assert np.to_charge(5, "USD") == (500, "USD")
    with pytest.raises(np.PaymentProviderError, match="crypto_currency_unsupported"):
        np.to_charge(5, "NGN")
    with pytest.raises(np.PaymentProviderError, match="crypto_bad_price"):
        np.to_charge(0, "GHS")


def test_to_charge_refuses_when_no_rate_is_available(monkeypatch):
    import xera.payments.nowpayments_provider as np
    monkeypatch.delenv("XERA_CRYPTO_GHS_PER_USD")
    import services.evosgpt.currency as fx
    monkeypatch.setattr(fx, "_load_rates", lambda: None)
    with pytest.raises(np.PaymentProviderError, match="crypto_rate_unavailable"):
        np.to_charge(150, "GHS")
    monkeypatch.setattr(fx, "_load_rates", lambda: {"USD": 0.0625})
    assert np.to_charge(160, "GHS") == (1000, "USD")


# ------------------------------------------------------------ purchase

def test_crypto_purchase_stores_usd_charge_and_creates_usdt_bsc_invoice(crypto_hr, fake_supabase, np_http):
    res, ref = _buy(crypto_hr, fake_supabase, np_http, price=150)
    sent = np_http.posts[0]
    assert sent["url"].endswith("/invoice") and sent["headers"]["x-api-key"] == API_KEY
    assert sent["json"]["price_amount"] == 10.0 and sent["json"]["price_currency"] == "usd"
    assert sent["json"]["pay_currency"] == "usdtbsc" and sent["json"]["order_id"] == ref
    assert sent["json"]["success_url"] == "https://evoshub.example/xera/?pay=crypto"
    pay = fake_supabase.store["xera_hashrate_payments"][0]
    assert pay["provider"] == "CRYPTO" and pay["charge_amount_minor"] == 1000 and pay["charge_currency"] == "USD"
    assert pay["asset"] == "USDT-BEP20"
    assert res["payment"]["invoice_url"].startswith("https://nowpayments.test/")
    assert res["charge"] == {"amount": 10.0, "currency": "USD", "asset": "USDT-BEP20"}


def test_crypto_purchase_releases_reservation_when_invoice_fails(crypto_hr, fake_supabase, np_http):
    np_http.invoice_status = 400
    _seed_tier(fake_supabase, tier_id=1, price=150, currency="GHS", daily_rate=5, duration_days=30)
    with pytest.raises(crypto_hr.PaymentProviderError):
        crypto_hr.purchase(user_id=1, tier_id=1, payment_method="CRYPTO")
    assert crypto_hr.get_entitlement_state()["reserved_amount"] == 0
    assert fake_supabase.store["xera_hashrate_payments"][0]["status"] == "FAILED"


def test_crypto_needs_the_api_key_and_ipn_secret(crypto_hr, fake_supabase, monkeypatch):
    _seed_tier(fake_supabase, tier_id=1, price=150, currency="GHS")
    monkeypatch.delenv("NOWPAYMENTS_IPN_SECRET")
    assert crypto_hr.payment_availability()["crypto"] is False
    with pytest.raises(crypto_hr.HashrateError, match="crypto_payments_not_yet_configured"):
        crypto_hr.purchase(user_id=1, tier_id=1, payment_method="CRYPTO")


# ------------------------------------------------------------ IPN -> activation

def test_finished_payment_activates_after_server_side_verification(crypto_hr, fake_supabase, np_http):
    _, ref = _buy(crypto_hr, fake_supabase, np_http)
    np_http.payments["777"] = _finished(ref)
    out = crypto_hr.handle_nowpayments_ipn({"order_id": ref, "payment_status": "finished", "payment_id": 777})
    assert out["handled"] is True and out["session"]["status"] == "ACTIVE"
    assert np_http.gets and np_http.gets[0]["url"].endswith("/payment/777") and np_http.gets[0]["headers"]["x-api-key"] == API_KEY
    assert fake_supabase.store["xera_hashrate_payments"][0]["tx_hash"] == "np-777"


def test_ipn_claiming_finished_does_not_activate_if_api_disagrees(crypto_hr, fake_supabase, np_http):
    _, ref = _buy(crypto_hr, fake_supabase, np_http)
    np_http.payments["777"] = _finished(ref, status="waiting")
    with pytest.raises(crypto_hr.HashrateError, match="payment_verification_failed"):
        crypto_hr.handle_nowpayments_ipn({"order_id": ref, "payment_status": "finished", "payment_id": 777})
    assert fake_supabase.store["xera_hashrate_sessions"][0]["status"] == "PENDING_PAYMENT"


def test_unknown_payment_id_does_not_activate(crypto_hr, fake_supabase, np_http):
    _, ref = _buy(crypto_hr, fake_supabase, np_http)
    with pytest.raises(crypto_hr.HashrateError, match="payment_verification_failed"):
        crypto_hr.handle_nowpayments_ipn({"order_id": ref, "payment_status": "finished", "payment_id": 999})


def test_payment_for_another_order_cannot_activate_this_one(crypto_hr, fake_supabase, np_http):
    _, ref = _buy(crypto_hr, fake_supabase, np_http)
    np_http.payments["777"] = _finished("xera-hr-someone-elses-order")
    with pytest.raises(crypto_hr.HashrateError, match="payment_verification_failed"):
        crypto_hr.handle_nowpayments_ipn({"order_id": ref, "payment_status": "finished", "payment_id": 777})


def test_wrong_coin_is_not_accepted(crypto_hr, fake_supabase, np_http):
    _, ref = _buy(crypto_hr, fake_supabase, np_http)
    np_http.payments["777"] = _finished(ref, pay_currency="btc")
    with pytest.raises(crypto_hr.HashrateError, match="payment_verification_failed"):
        crypto_hr.handle_nowpayments_ipn({"order_id": ref, "payment_status": "finished", "payment_id": 777})


def test_underpriced_payment_is_rejected_by_the_stored_charge_check(crypto_hr, fake_supabase, np_http):
    _, ref = _buy(crypto_hr, fake_supabase, np_http, price=150)         # stored charge: 10.00 USD
    np_http.payments["777"] = _finished(ref, price=1.0)                  # NOWPayments says only $1 invoice settled
    with pytest.raises(crypto_hr.HashrateError, match="payment_verification_failed"):
        crypto_hr.handle_nowpayments_ipn({"order_id": ref, "payment_status": "finished", "payment_id": 777})
    assert fake_supabase.store["xera_hashrate_sessions"][0]["status"] == "PENDING_PAYMENT"


def test_replayed_ipn_is_idempotent_and_a_payment_id_cannot_buy_twice(crypto_hr, fake_supabase, np_http):
    _, ref = _buy(crypto_hr, fake_supabase, np_http)
    np_http.payments["777"] = _finished(ref)
    ipn = {"order_id": ref, "payment_status": "finished", "payment_id": 777}
    first = crypto_hr.handle_nowpayments_ipn(ipn)
    again = crypto_hr.handle_nowpayments_ipn(ipn)
    assert first["session"]["status"] == again["session"]["status"] == "ACTIVE"
    assert len([p for p in fake_supabase.store["xera_hashrate_payments"] if p["status"] == "CONFIRMED"]) == 1

    # a second purchase can't be confirmed with the SAME NOWPayments payment id
    _seed_tier(fake_supabase, tier_id=2, price=150, currency="GHS", daily_rate=5, duration_days=30)
    ref2 = crypto_hr.purchase(user_id=1, tier_id=2, payment_method="CRYPTO")["reference"]
    np_http.payments["777"] = _finished(ref2)
    with pytest.raises(crypto_hr.HashrateError, match="tx_hash_already_used"):
        crypto_hr.handle_nowpayments_ipn({"order_id": ref2, "payment_status": "finished", "payment_id": 777})


def test_failed_and_expired_release_the_reservation(crypto_hr, fake_supabase, np_http):
    _, ref = _buy(crypto_hr, fake_supabase, np_http)
    assert crypto_hr.get_entitlement_state()["reserved_amount"] == 150
    out = crypto_hr.handle_nowpayments_ipn({"order_id": ref, "payment_status": "expired", "payment_id": 1})
    assert out["handled"] is True
    assert crypto_hr.get_entitlement_state()["reserved_amount"] == 0
    assert fake_supabase.store["xera_hashrate_payments"][0]["status"] == "EXPIRED"


def test_partially_paid_and_foreign_orders_are_ignored(crypto_hr, fake_supabase, np_http):
    _, ref = _buy(crypto_hr, fake_supabase, np_http)
    assert crypto_hr.handle_nowpayments_ipn({"order_id": ref, "payment_status": "partially_paid", "payment_id": 1}) == {"handled": False}
    assert crypto_hr.handle_nowpayments_ipn({"order_id": "other-shop-1", "payment_status": "finished", "payment_id": 1}) == {"handled": False}
    assert fake_supabase.store["xera_hashrate_sessions"][0]["status"] == "PENDING_PAYMENT"


# ------------------------------------------------------------ webhook route

@pytest.fixture
def client(crypto_hr, fake_supabase):
    sys.modules.pop("xera.routes_hashrate", None)
    sys.modules.pop("xera.routes_readiness", None)
    import xera.routes_hashrate as rh
    import xera.routes_readiness as rr
    import xera.user_auth as ua
    app = FastAPI()
    app.include_router(rh.router, prefix="/api/xera/hashrate")
    app.include_router(rr.router, prefix="/api/xera")
    c = TestClient(app)
    c.bearer = lambda uid: {"Authorization": f"Bearer {ua.make_user_token(uid)}"}
    return c


def test_webhook_rejects_bad_signature_and_activates_on_good_one(client, crypto_hr, fake_supabase, np_http):
    _, ref = _buy(crypto_hr, fake_supabase, np_http)
    np_http.payments["777"] = _finished(ref)
    body = {"order_id": ref, "payment_status": "finished", "payment_id": 777}
    raw, sig = _sign(body)
    url = "/api/xera/hashrate/webhooks/nowpayments"

    assert client.post(url, content=raw, headers={"x-nowpayments-sig": "bad"}).status_code == 401
    assert client.post(url, content=raw).status_code == 401
    assert fake_supabase.store["xera_hashrate_sessions"][0]["status"] == "PENDING_PAYMENT"

    ok = client.post(url, content=raw, headers={"x-nowpayments-sig": sig})
    assert ok.status_code == 200 and ok.json()["session"]["status"] == "ACTIVE"


def test_webhook_fails_closed_without_ipn_secret(client, monkeypatch):
    monkeypatch.delenv("NOWPAYMENTS_IPN_SECRET")
    raw, sig = _sign({"order_id": "xera-hr-1", "payment_status": "finished"})
    r = client.post("/api/xera/hashrate/webhooks/nowpayments", content=raw, headers={"x-nowpayments-sig": sig})
    assert r.status_code == 503


# ------------------------------------------------------------ transfer fee

def _fee_row(fake, uid):
    return next((r for r in fake.store.get("xera_transfer_fee", []) if r["user_id"] == uid), None)


def test_fee_pay_route_creates_a_one_dollar_usdt_invoice(client, fake_supabase, np_http, monkeypatch):
    monkeypatch.setenv("XERA_FEE_SUCCESS_URL", "https://evoshub.example/xera/?fee=return")
    r = client.post("/api/xera/fee/pay", headers=client.bearer(1))
    assert r.status_code == 200
    pay = r.json()["payment"]
    assert pay["invoice_url"].startswith("https://nowpayments.test/") and pay["reference"].startswith("xera-fee-1-")
    sent = np_http.posts[0]["json"]
    assert sent["price_amount"] == 1.0 and sent["price_currency"] == "usd" and sent["pay_currency"] == "usdtbsc"
    assert sent["success_url"] == "https://evoshub.example/xera/?fee=return"
    assert _fee_row(fake_supabase, 1)["status"] == "PENDING"     # not PAID until a verified IPN


def test_fee_pay_requires_login_and_an_open_collection_flag(client, fake_supabase, np_http, monkeypatch):
    assert client.post("/api/xera/fee/pay").status_code == 401
    monkeypatch.setenv("XERA_FEE_COLLECTION_ENABLED", "false")
    assert client.post("/api/xera/fee/pay", headers=client.bearer(1)).status_code == 403
    assert np_http.posts == []


def test_fee_is_paid_only_after_verified_finished_payment_of_exact_amount(client, fake_supabase, np_http):
    ref = client.post("/api/xera/fee/pay", headers=client.bearer(1)).json()["payment"]["reference"]
    url = "/api/xera/hashrate/webhooks/nowpayments"
    body = {"order_id": ref, "payment_status": "finished", "payment_id": 55}

    # NOWPayments' API says it is still waiting -> not paid, and the webhook asks for a retry
    np_http.payments["55"] = _finished(ref, payment_id="55", price=1.0, status="confirming")
    raw, sig = _sign(body)
    assert client.post(url, content=raw, headers={"x-nowpayments-sig": sig}).status_code == 400
    assert _fee_row(fake_supabase, 1)["status"] == "PENDING"

    # wrong amount -> acked (retry cannot fix it) but NOT paid
    np_http.payments["55"] = _finished(ref, payment_id="55", price=0.5)
    assert client.post(url, content=raw, headers={"x-nowpayments-sig": sig}).json()["handled"] is False
    assert _fee_row(fake_supabase, 1)["status"] == "PENDING"

    # exact $1.00 USDT-BSC -> PAID, and the readiness gate now accepts it
    np_http.payments["55"] = _finished(ref, payment_id="55", price=1.0)
    ok = client.post(url, content=raw, headers={"x-nowpayments-sig": sig})
    assert ok.status_code == 200 and ok.json()["paid"] is True
    row = _fee_row(fake_supabase, 1)
    assert row["status"] == "PAID" and row["payment_reference"] == ref and row["amount_minor"] == 100 and row["currency"] == "USD"
    import xera.readiness as readiness
    assert readiness.get_fee(1)["status"] == "PAID"
    assert any(n["kind"] == "fee_paid" for n in fake_supabase.store["xera_notifications"])

    # replay is a no-op; a second payment by the same user is flagged, never overwrites
    assert client.post(url, content=raw, headers={"x-nowpayments-sig": sig}).json()["already_paid"] is True
    ref2 = "xera-fee-1-" + "b" * 32
    np_http.payments["56"] = _finished(ref2, payment_id="56", price=1.0)
    raw2, sig2 = _sign({"order_id": ref2, "payment_status": "finished", "payment_id": 56})
    assert client.post(url, content=raw2, headers={"x-nowpayments-sig": sig2}).json()["needs_refund"] is True
    assert _fee_row(fake_supabase, 1)["payment_reference"] == ref


def test_fee_cannot_be_started_once_paid(client, fake_supabase, np_http):
    fake_supabase.store["xera_transfer_fee"] = [{
        "user_id": 1, "status": "PAID", "payment_reference": "x", "paid_at": "2026-10-24T00:00:00Z",
        "amount_minor": 100, "currency": "USD"}]
    assert client.post("/api/xera/fee/pay", headers=client.bearer(1)).status_code == 409
    assert np_http.posts == []


def test_failed_fee_invoice_marks_pending_row_failed(client, fake_supabase, np_http):
    ref = client.post("/api/xera/fee/pay", headers=client.bearer(1)).json()["payment"]["reference"]
    raw, sig = _sign({"order_id": ref, "payment_status": "expired", "payment_id": 1})
    assert client.post("/api/xera/hashrate/webhooks/nowpayments", content=raw, headers={"x-nowpayments-sig": sig}).status_code == 200
    assert _fee_row(fake_supabase, 1)["status"] == "FAILED"
