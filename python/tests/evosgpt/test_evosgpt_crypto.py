"""EVOSGPT plans paid with USDT (NOWPayments). NOWPayments itself is faked; the rest is the real route code."""
import pytest

from tests.evosgpt.test_evosgpt_xera_discount import _hdr  # noqa: F401  (same signed-in header helper)


@pytest.fixture()
def crypto(env, monkeypatch):
    c = env.core
    monkeypatch.setenv("NOWPAYMENTS_API_KEY", "k")
    monkeypatch.setenv("NOWPAYMENTS_IPN_SECRET", "s")
    monkeypatch.setenv("XERA_NOWPAYMENTS_IPN_URL", "https://api.example/ipn")
    monkeypatch.setenv("XERA_CRYPTO_GHS_PER_USD", "10")        # GH₵20 -> $2.00, GH₵70 -> $7.00
    seen = {"init": [], "verify": {"confirmed": True, "currency": "USD", "amount_minor": 200}}

    def fake_init(self, **kw):
        seen["init"].append(kw)
        return {"invoice_url": "https://nowpayments.io/payment/?iid=1", "invoice_id": "1"}

    monkeypatch.setattr(c.nowpayments.NowPaymentsProvider, "initialize", fake_init)
    monkeypatch.setattr(c.nowpayments.NowPaymentsProvider, "verify", lambda self, **kw: dict(seen["verify"]))
    env.seen = seen
    return env


def _init(env, **extra):
    return env.client.post("/api/evosgpt/upgrade/init",
                           json={"user_id": 1, "tier": "Pro", "email": "a@b.c", "method": "crypto", **extra},
                           headers=_hdr(env.core, 1))


def test_crypto_init_creates_an_invoice_at_the_usd_price_and_stores_it(crypto):
    r = _init(crypto)
    assert r.status_code == 200
    body = r.json()
    assert body["payment_url"].startswith("https://nowpayments.io/") and body["billing_currency"] == "USD" and body["billing_amount"] == 2.0
    k = crypto.seen["init"][0]
    assert k["amount"] == 2.0 and k["currency"] == "USD" and k["metadata"]["product"] == "evosgpt_plan" and k["reference"] == body["reference"]
    row = crypto.db.t["evosgpt_purchases"][0]
    assert row["payment_method"] == "crypto" and row["crypto_usd_cents"] == 200 and row["status"] == "pending"


def test_crypto_never_touches_paystack(crypto, monkeypatch):
    monkeypatch.setattr(crypto.core.requests, "post", lambda *a, **k: pytest.fail("Paystack must not be called"))
    monkeypatch.setattr(crypto.core, "PAYSTACK_SECRET", "")
    assert _init(crypto).status_code == 200


def test_xera_discount_cannot_be_combined_with_crypto(crypto):
    assert _init(crypto, use_xera=True).status_code == 400
    assert crypto.db.t.get("evosgpt_purchases", []) == []


def test_unknown_method_is_refused(crypto):
    assert _init(crypto, method="bitcoin").status_code == 400


def test_crypto_is_refused_when_not_configured_or_switched_off(crypto, monkeypatch):
    monkeypatch.setenv("EVOSGPT_CRYPTO_ENABLED", "false")
    assert _init(crypto).status_code == 503
    monkeypatch.delenv("EVOSGPT_CRYPTO_ENABLED")
    monkeypatch.delenv("XERA_NOWPAYMENTS_IPN_URL")
    assert _init(crypto).status_code == 503


def test_methods_endpoint_reports_prices_and_fails_closed(crypto, monkeypatch):
    m = crypto.client.get("/api/evosgpt/upgrade/methods").json()
    assert m["crypto"]["enabled"] is True and m["crypto"]["usd"] == {"Pro": 2.0, "Core": 7.0}
    monkeypatch.delenv("NOWPAYMENTS_API_KEY")
    assert crypto.client.get("/api/evosgpt/upgrade/methods").json()["crypto"] == {"enabled": False, "usd": {}}


def _ipn(env, ref, status="finished"):
    return env.core.handle_nowpayments_ipn({"order_id": ref, "payment_status": status, "payment_id": 99})


def test_finished_payment_activates_the_plan_once(crypto):
    ref = _init(crypto).json()["reference"]
    assert _ipn(crypto, ref) == {"handled": True, "result": "success"}
    assert crypto.db.t["users"][0]["evosgpt_tier"] == "Pro"
    assert crypto.db.t["evosgpt_purchases"][0]["status"] == "paid"
    assert _ipn(crypto, ref) == {"handled": True, "result": "already_processed"}


def test_unfinished_statuses_do_nothing(crypto):
    ref = _init(crypto).json()["reference"]
    for s in ("waiting", "confirming", "partially_paid", "failed", "expired"):
        assert _ipn(crypto, ref, s)["handled"] is False
    assert crypto.db.t["users"][0]["evosgpt_tier"] == "Basic"


def test_underpaid_or_wrong_asset_never_activates(crypto):
    ref = _init(crypto).json()["reference"]
    crypto.seen["verify"] = {"confirmed": True, "currency": "USD", "amount_minor": 150}   # less than the stored $2.00
    assert _ipn(crypto, ref)["handled"] is False
    crypto.seen["verify"] = {"confirmed": True, "currency": "EUR", "amount_minor": 999}
    assert _ipn(crypto, ref)["handled"] is False
    crypto.seen["verify"] = {"confirmed": False}
    assert _ipn(crypto, ref)["handled"] is False
    assert crypto.db.t["users"][0]["evosgpt_tier"] == "Basic"


def test_ipn_for_a_card_purchase_or_unknown_reference_is_ignored(crypto):
    crypto.db.t.setdefault("evosgpt_purchases", []).append(
        {"user_id": 1, "tier": "Pro", "reference": "EVOS-GPT-1-ABCDEF12", "status": "pending", "payment_method": "paystack"})
    assert _ipn(crypto, "EVOS-GPT-1-ABCDEF12")["handled"] is False
    assert _ipn(crypto, "EVOS-GPT-1-00000000")["handled"] is False
    assert crypto.db.t["users"][0]["evosgpt_tier"] == "Basic"


def test_verify_endpoint_waits_for_the_ipn_for_crypto(crypto):
    ref = _init(crypto).json()["reference"]
    r = crypto.client.get(f"/api/evosgpt/upgrade/verify/{ref}", headers=_hdr(crypto.core, 1)).json()
    assert r["paid"] is False and r["pending"] is True
    _ipn(crypto, ref)
    r = crypto.client.get(f"/api/evosgpt/upgrade/verify/{ref}", headers=_hdr(crypto.core, 1)).json()
    assert r["paid"] is True and r["tier"] == "Pro"
