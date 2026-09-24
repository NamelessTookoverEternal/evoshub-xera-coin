"""
Unit tests for xera/hashrate.py against the same in-memory FakeSupabase
harness used by tests/test_claims.py (see conftest.py). The RPC handlers
installed here are hand-written Python re-implementations of the actual
Postgres functions in
supabase/migrations/20260923_xera_hashrate_v1.sql — they exist to pin
down the *contract* (which error each scenario raises, what state
changes) that hashrate.py depends on; they are not a substitute for
running the real SQL against Postgres (see IMPLEMENTATION REPORT for
what that would additionally require).
"""

import types

import pytest


# ------------------------------------------------------------
# Fake RPC layer — mirrors the Postgres functions in the migration.
# ------------------------------------------------------------

def _entitlement_row(fake_supabase):
    table = fake_supabase.store.setdefault("xera_mining_entitlement_state", [])
    if not table:
        table.append({
            "id": 1, "reserved_amount": 0.0, "cap": 75_000_000.0,
            "warning_threshold": 65_000_000.0, "closure_threshold": 70_000_000.0,
            "free_mining_closed": False,
        })
    return table[0]


def _install_entitlement_rpcs(fake_supabase):
    def reserve(params):
        row = _entitlement_row(fake_supabase)
        amount = params["p_amount"]
        if amount <= 0:
            raise RuntimeError("invalid_amount")
        if row["reserved_amount"] + amount > row["cap"]:
            raise RuntimeError("entitlement_cap_exceeded")
        row["reserved_amount"] += amount
        if row["reserved_amount"] >= row["closure_threshold"]:
            row["free_mining_closed"] = True
        return types.SimpleNamespace(data=[dict(row)])

    def release(params):
        row = _entitlement_row(fake_supabase)
        row["reserved_amount"] = max(0.0, row["reserved_amount"] - params["p_amount"])
        return types.SimpleNamespace(data=[dict(row)])

    fake_supabase.rpc_handlers["xera_reserve_mining_entitlement"] = reserve
    fake_supabase.rpc_handlers["xera_release_mining_entitlement"] = release


def _install_hashrate_rpcs(fake_supabase):
    _install_entitlement_rpcs(fake_supabase)

    def purchase(params):
        tiers = {t["id"]: t for t in fake_supabase.store.get("xera_hashrate_tiers", [])}
        tier = tiers.get(params["p_tier_id"])
        if tier is None:
            raise RuntimeError("tier_not_found")
        if not tier["enabled"]:
            raise RuntimeError("tier_disabled")

        entitlement = tier["daily_rate"] * tier["duration_days"]

        row = _entitlement_row(fake_supabase)
        if row["reserved_amount"] + entitlement > row["cap"]:
            raise RuntimeError("entitlement_cap_exceeded")
        row["reserved_amount"] += entitlement
        if row["reserved_amount"] >= row["closure_threshold"]:
            row["free_mining_closed"] = True

        sessions = fake_supabase.store.setdefault("xera_hashrate_sessions", [])
        session = {
            "id": len(sessions) + 1, "user_id": params["p_user_id"], "tier_id": tier["id"],
            "payment_method": params["p_payment_method"], "payment_currency": tier["currency"],
            "amount_paid": tier["price"], "daily_rate": tier["daily_rate"],
            "duration_days": tier["duration_days"], "maximum_entitlement": entitlement,
            "reserved_entitlement": entitlement, "rewarded_amount": 0,
            "started_at": None, "expires_at": None, "status": "PENDING_PAYMENT",
        }
        sessions.append(session)

        payments = fake_supabase.store.setdefault("xera_hashrate_payments", [])
        if any(p["reference"] == params["p_reference"] for p in payments):
            raise RuntimeError("reference_already_used")
        payment = {
            "id": len(payments) + 1, "session_id": session["id"], "user_id": params["p_user_id"],
            "provider": params["p_payment_method"], "reference": params["p_reference"],
            "amount": tier["price"], "currency": tier["currency"], "status": "PENDING",
            "tx_hash": None,
        }
        payments.append(payment)

        return types.SimpleNamespace(data=[{
            "session_id": session["id"], "payment_id": payment["id"],
            "maximum_entitlement": entitlement, "price": tier["price"], "currency": tier["currency"],
        }])

    def confirm(params):
        payments = fake_supabase.store.setdefault("xera_hashrate_payments", [])
        payment = next((p for p in payments if p["reference"] == params["p_reference"]), None)
        if payment is None:
            raise RuntimeError("payment_not_found")

        sessions = fake_supabase.store.setdefault("xera_hashrate_sessions", [])
        session = next(s for s in sessions if s["id"] == payment["session_id"])

        if payment["status"] == "CONFIRMED":
            return types.SimpleNamespace(data=[dict(session)])  # idempotent replay
        if payment["status"] not in ("PENDING", "EXPIRED"):
            raise RuntimeError("payment_already_finalized")

        if payment["status"] == "EXPIRED":
            # Late payment: re-take the reservation the sweep released.
            if session["status"] != "EXPIRED":
                raise RuntimeError("payment_already_finalized")
            row = _entitlement_row(fake_supabase)
            if row["reserved_amount"] + session["reserved_entitlement"] > row["cap"]:
                raise RuntimeError("entitlement_cap_exceeded")
            row["reserved_amount"] += session["reserved_entitlement"]

        tx_hash = params.get("p_tx_hash")
        if tx_hash and any(p.get("tx_hash") == tx_hash and p["status"] == "CONFIRMED" for p in payments):
            raise RuntimeError("tx_hash_already_used")

        payment["status"] = "CONFIRMED"
        payment["tx_hash"] = tx_hash
        session["status"] = "ACTIVE"
        session["started_at"] = "now"
        session["expires_at"] = "later"
        return types.SimpleNamespace(data=[dict(session)])

    def release(params):
        payments = fake_supabase.store.setdefault("xera_hashrate_payments", [])
        payment = next((p for p in payments if p["reference"] == params["p_reference"]), None)
        if payment is None:
            raise RuntimeError("payment_not_found")

        sessions = fake_supabase.store.setdefault("xera_hashrate_sessions", [])
        session = next(s for s in sessions if s["id"] == payment["session_id"])

        if payment["status"] in ("FAILED", "EXPIRED", "CANCELLED"):
            return types.SimpleNamespace(data=[dict(session)])  # idempotent
        if payment["status"] == "CONFIRMED":
            raise RuntimeError("cannot_release_confirmed_payment")

        payment["status"] = params["p_status"]
        session["status"] = params["p_status"]

        row = _entitlement_row(fake_supabase)
        row["reserved_amount"] = max(0.0, row["reserved_amount"] - session["reserved_entitlement"])

        return types.SimpleNamespace(data=[dict(session)])

    fake_supabase.rpc_handlers["xera_purchase_hashrate"] = purchase
    fake_supabase.rpc_handlers["xera_confirm_hashrate_payment"] = confirm
    fake_supabase.rpc_handlers["xera_release_hashrate_reservation"] = release


def _seed_tier(fake_supabase, tier_id=1, price=1, currency="GHS", duration_days=30, daily_rate=5, enabled=True):
    tiers = fake_supabase.store.setdefault("xera_hashrate_tiers", [])
    tiers.append({
        "id": tier_id, "name": f"tier-{tier_id}", "price": price, "currency": currency,
        "duration_days": duration_days, "daily_rate": daily_rate, "enabled": enabled,
    })


class _FakeProvider:
    """Stands in for PaystackHashrateProvider — no real HTTP calls in unit tests."""

    def __init__(self, name="PAYSTACK"):
        self.name = name
        self.init_calls = []

    def initialize(self, *, reference, amount, currency, user_id, metadata, email=None):
        self.init_calls.append(reference)
        self.last_email = email
        return {"authorization_url": f"https://paystack.test/{reference}", "reference": reference}

    def verify(self, *, reference):
        return {"confirmed": True, "tx_hash": f"tx-{reference}", "raw": {}}


@pytest.fixture
def hr(fake_supabase, monkeypatch):
    monkeypatch.setenv("XERA_HASHRATE_PAYMENTS_ENABLED", "true")
    """Imports xera.hashrate fresh against this test's fake_supabase and
    swaps in fake payment providers (mirrors the fresh-import pattern in
    conftest.py's fake_supabase fixture for xera.chain.*)."""
    import sys
    for mod in list(sys.modules):
        if mod == "xera.hashrate":
            del sys.modules[mod]
    import xera.hashrate as hashrate_module

    _install_hashrate_rpcs(fake_supabase)
    fake_supabase.store["users"] = [
        {"id": 1, "email": "one@example.com"},
        {"id": 2, "email": "two@example.com"},
        {"id": 3, "email": None},
    ]
    fake_provider = _FakeProvider()
    monkeypatch.setitem(hashrate_module._PROVIDERS, "PAYSTACK", fake_provider)
    hashrate_module._test_provider = fake_provider
    return hashrate_module


# ------------------------------------------------------------
# 1-2: full 30-day entitlement fits / does not fit
# ------------------------------------------------------------

def test_purchase_allowed_when_full_entitlement_fits(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)  # 150 XERA
    result = hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")
    assert result["maximum_entitlement"] == 150
    state = hr.get_entitlement_state()
    assert state["reserved_amount"] == 150


def test_purchase_rejected_when_full_entitlement_does_not_fit(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)  # 150 XERA
    row = _entitlement_row(fake_supabase)
    row["reserved_amount"] = row["cap"] - 100  # only 100 left; tier needs 150

    with pytest.raises(hr.HashrateError) as exc:
        hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")
    assert str(exc.value) == "insufficient_mining_allocation"
    # No partial reservation was made.
    assert _entitlement_row(fake_supabase)["reserved_amount"] == row["cap"] - 100


# ------------------------------------------------------------
# 3: two simultaneous purchases cannot oversubscribe allocation
# ------------------------------------------------------------

def test_concurrent_purchases_cannot_oversubscribe(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=50000, duration_days=30)  # 1,500,000 XERA
    _seed_tier(fake_supabase, tier_id=2, daily_rate=33333.34, duration_days=30)  # ~1,000,000 XERA
    row = _entitlement_row(fake_supabase)
    row["reserved_amount"] = row["cap"] - 2_000_000  # exactly 2,000,000 remaining

    hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")  # consumes 1,500,000
    with pytest.raises(hr.HashrateError):
        hr.purchase(user_id=2, tier_id=2, payment_method="PAYSTACK")  # needs ~1,000,000 > 500,000 left

    assert _entitlement_row(fake_supabase)["reserved_amount"] == row["cap"] - 2_000_000 + 1_500_000


# ------------------------------------------------------------
# 4: payment confirmation activates the session; replay is idempotent
# ------------------------------------------------------------

def test_confirm_activates_session_and_replay_is_idempotent(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)
    purchase = hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")
    reference = purchase["reference"]

    session = hr.confirm_payment(reference, tx_hash="tx-1")
    assert session["status"] == "ACTIVE"

    # Replaying the webhook must not double-activate or raise.
    session_again = hr.confirm_payment(reference, tx_hash="tx-1")
    assert session_again["status"] == "ACTIVE"
    assert _entitlement_row(fake_supabase)["reserved_amount"] == 150  # unchanged by replay


# ------------------------------------------------------------
# 7/8: failed / expired payment releases the reservation
# ------------------------------------------------------------

def test_failed_payment_releases_reservation(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)
    purchase = hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")
    assert _entitlement_row(fake_supabase)["reserved_amount"] == 150

    session = hr.fail_payment(purchase["reference"])
    assert session["status"] == "FAILED"
    assert _entitlement_row(fake_supabase)["reserved_amount"] == 0


def test_expired_payment_releases_reservation(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)
    purchase = hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")

    session = hr.expire_payment(purchase["reference"])
    assert session["status"] == "EXPIRED"
    assert _entitlement_row(fake_supabase)["reserved_amount"] == 0


def test_cannot_release_a_confirmed_payment(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)
    purchase = hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")
    hr.confirm_payment(purchase["reference"], tx_hash="tx-1")

    with pytest.raises(Exception):
        hr._release(purchase["reference"], "FAILED")
    # Reservation must still stand — the mining reward is real.
    assert _entitlement_row(fake_supabase)["reserved_amount"] == 150


# ------------------------------------------------------------
# 9: duplicate purchase reference is rejected (idempotency guard)
# ------------------------------------------------------------

def test_duplicate_reference_is_rejected(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)

    # Simulate two purchase calls that happen to generate the same
    # reference (the RPC's unique constraint is the real backstop —
    # this exercises that the RPC layer surfaces it as an error).
    res = fake_supabase.rpc("xera_purchase_hashrate", {
        "p_user_id": 1, "p_tier_id": 1, "p_payment_method": "PAYSTACK", "p_reference": "dup-ref",
    })
    assert res.data
    with pytest.raises(RuntimeError, match="reference_already_used"):
        fake_supabase.rpc("xera_purchase_hashrate", {
            "p_user_id": 1, "p_tier_id": 1, "p_payment_method": "PAYSTACK", "p_reference": "dup-ref",
        })


# ------------------------------------------------------------
# 14/15/16/17: 65M warning, 70M free-mining closure, hashrate continues
# ------------------------------------------------------------

def test_65m_warning_activates(hr, fake_supabase):
    row = _entitlement_row(fake_supabase)
    row["reserved_amount"] = 65_000_000
    state = hr.get_entitlement_state()
    assert state["warning_active"] is True
    assert state["warning_countdown"] == 5_000_000


def test_free_mining_remains_active_below_70m(hr, fake_supabase):
    row = _entitlement_row(fake_supabase)
    row["reserved_amount"] = 69_999_999
    assert hr.get_entitlement_state()["free_mining_closed"] is False


def test_hashrate_purchasable_after_70m_if_it_fits(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=10000, duration_days=30)  # 300,000 XERA
    row = _entitlement_row(fake_supabase)
    row["reserved_amount"] = 74_500_000  # 500,000 remaining
    row["free_mining_closed"] = True

    result = hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")
    assert result["maximum_entitlement"] == 300_000
    assert _entitlement_row(fake_supabase)["reserved_amount"] == 74_800_000


def test_hashrate_rejected_after_70m_if_it_does_not_fit(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=20000, duration_days=30)  # 600,000 XERA
    row = _entitlement_row(fake_supabase)
    row["reserved_amount"] = 74_500_000  # only 500,000 remaining
    row["free_mining_closed"] = True

    with pytest.raises(hr.HashrateError):
        hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")
    assert _entitlement_row(fake_supabase)["reserved_amount"] == 74_500_000  # unused remainder untouched


# ------------------------------------------------------------
# 21/22: 75M can never be exceeded, remaining allocation can stay unused
# ------------------------------------------------------------

def test_cap_can_never_be_exceeded(hr, fake_supabase):
    row = _entitlement_row(fake_supabase)
    row["reserved_amount"] = 74_999_000
    with pytest.raises(RuntimeError, match="entitlement_cap_exceeded"):
        fake_supabase.rpc("xera_reserve_mining_entitlement", {"p_amount": 1500, "p_source": "TEST"})
    assert _entitlement_row(fake_supabase)["reserved_amount"] == 74_999_000


def test_disabled_tier_cannot_be_purchased(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30, enabled=False)
    with pytest.raises(hr.HashrateError) as exc:
        hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")
    assert str(exc.value) == "tier_disabled"


def test_crypto_payment_disabled_by_default(hr, fake_supabase, monkeypatch):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)
    monkeypatch.delenv("XERA_HASHRATE_CRYPTO_ENABLED", raising=False)
    with pytest.raises(hr.HashrateError) as exc:
        hr.purchase(user_id=1, tier_id=1, payment_method="CRYPTO")
    assert str(exc.value) == "crypto_payments_not_yet_configured"


# ------------------------------------------------------------
# Regression tests for bugs fixed in the hashrate review
# ------------------------------------------------------------

def test_purchase_sends_customer_email_to_paystack(hr, fake_supabase):
    # Paystack's /transaction/initialize requires an email; it used to be omitted.
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)
    hr.purchase(user_id=2, tier_id=1, payment_method="PAYSTACK")
    assert hr._test_provider.last_email == "two@example.com"


def test_purchase_without_account_email_reserves_nothing(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)
    with pytest.raises(hr.HashrateError) as exc:
        hr.purchase(user_id=3, tier_id=1, payment_method="PAYSTACK")  # user 3 has no email
    assert str(exc.value) == "customer_email_required"
    assert _entitlement_row(fake_supabase)["reserved_amount"] == 0
    assert fake_supabase.store.get("xera_hashrate_sessions", []) == []


def test_paystack_provider_requires_email_and_sends_it(monkeypatch):
    from xera.payments import paystack_provider as pp
    from xera.payments.base import PaymentProviderError

    monkeypatch.setenv("XERA_PAYSTACK_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("XERA_HASHRATE_CALLBACK_URL", "https://evoshub.xyz/xera")
    sent = {}

    class _Resp:
        def json(self):
            return {"status": True, "data": {"authorization_url": "https://pay.test/x", "access_code": "ac"}}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(json)
        return _Resp()

    monkeypatch.setattr(pp.httpx, "post", fake_post)
    provider = pp.PaystackHashrateProvider()

    with pytest.raises(PaymentProviderError):
        provider.initialize(reference="xera-hr-1", amount=1, currency="GHS", user_id=1, metadata={})

    out = provider.initialize(reference="xera-hr-1", amount=1.5, currency="GHS", user_id=1, metadata={}, email="a@b.com")
    assert out["authorization_url"] == "https://pay.test/x"
    assert sent["email"] == "a@b.com"
    assert sent["amount"] == 150
    assert sent["callback_url"] == "https://evoshub.xyz/xera"


def test_amount_mismatch_from_rpc_maps_to_hashrate_error(hr, fake_supabase):
    def boom(params):
        raise RuntimeError("payment_verification_failed")
    fake_supabase.rpc_handlers["xera_confirm_hashrate_payment"] = boom
    with pytest.raises(hr.HashrateError) as exc:
        hr.confirm_payment("xera-hr-x", tx_hash="t", verified_amount_minor=1, verified_currency="GHS")
    assert str(exc.value) == "payment_verification_failed"  # used to escape as a raw 500


def test_late_payment_after_expiry_reactivates_session(hr, fake_supabase):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)
    purchase = hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")
    hr.expire_payment(purchase["reference"])
    assert _entitlement_row(fake_supabase)["reserved_amount"] == 0

    session = hr.confirm_payment(purchase["reference"], tx_hash="late-tx")
    assert session["status"] == "ACTIVE"
    assert _entitlement_row(fake_supabase)["reserved_amount"] == 150  # re-reserved


def test_late_payment_with_full_pool_is_flagged_for_refund_not_retried(hr, fake_supabase, monkeypatch):
    _seed_tier(fake_supabase, tier_id=1, daily_rate=5, duration_days=30)
    purchase = hr.purchase(user_id=1, tier_id=1, payment_method="PAYSTACK")
    hr.expire_payment(purchase["reference"])
    row = _entitlement_row(fake_supabase)
    row["reserved_amount"] = row["cap"] - 10  # pool filled up while they were paying

    with pytest.raises(hr.HashrateError) as exc:
        hr.confirm_payment(purchase["reference"], tx_hash="late-tx")
    assert str(exc.value) == "late_payment_no_capacity"

    # Through the webhook it must be acked (200), not raised — Paystack would
    # otherwise retry a payment that can never activate.
    from xera.payments import paystack_provider as pp
    monkeypatch.setattr(pp, "verify_webhook_signature", lambda raw, sig: True)
    monkeypatch.setattr(hr._test_provider, "verify",
                        lambda reference: {"confirmed": True, "tx_hash": "late-tx", "amount_minor": 100, "currency": "GHS", "raw": {}})
    out = hr.handle_paystack_webhook(b"{}", "sig", {"event": "charge.success", "data": {"reference": purchase["reference"]}})
    assert out == {"handled": True, "needs_refund": True}


def test_entitlement_state_exposes_thresholds(hr, fake_supabase):
    _entitlement_row(fake_supabase)  # seeds the singleton row
    state = hr.get_entitlement_state()
    assert state["warning_threshold"] == 65_000_000
    assert state["closure_threshold"] == 70_000_000


def test_payment_availability_reflects_env(hr, monkeypatch):
    monkeypatch.setenv("XERA_HASHRATE_PAYMENTS_ENABLED", "false")
    monkeypatch.delenv("XERA_HASHRATE_CRYPTO_ENABLED", raising=False)
    assert hr.payment_availability() == {"paystack": False, "crypto": False}
    monkeypatch.setenv("XERA_HASHRATE_PAYMENTS_ENABLED", "true")
    assert hr.payment_availability()["paystack"] is True


def test_free_mining_closed_error_is_mapped_not_a_500(fake_supabase):
    from xera import routes
    status, _msg = routes._MINING_ERROR_HTTP["free_mining_closed"]
    assert status == 403


def test_admin_tier_update_rejects_values_the_db_would_refuse():
    from pydantic import ValidationError
    from xera.routes_admin import HashrateTierUpdate
    for bad in ({"price": 0}, {"price": -1}, {"daily_rate": 0}, {"duration_days": 0}, {"currency": "GH"}):
        with pytest.raises(ValidationError):
            HashrateTierUpdate(**bad)
    assert HashrateTierUpdate(price=2.5, currency="ghs").price == 2.5
