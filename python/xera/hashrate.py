"""
XERA hashrate service.

A hashrate is a paid 30-day mining session. It never mints XERA outside
the existing 75,000,000 canonical mining entitlement pool
(xera_mining_entitlement_state — see the architecture note at the top
of supabase/migrations/20260923_xera_hashrate_v1.sql for why that's a
new table rather than the existing on-chain-claim
xera_mining_allocation_state).

Payment and mining entitlement are deliberately different ledger
concepts (section 9/11 of the brief): xera_hashrate_payments records
"user paid"; the reward itself is bounded by the canonical mining pool,
recorded in xera_hashrate_sessions.reserved_entitlement. A purchase
reserves the FULL 30-day entitlement atomically before payment is even
initialized — see xera_purchase_hashrate — so a session can never start
and then be cut off partway through, and never accepts payment for a
session it can't fully back.

All DB writes that need to be atomic happen inside Postgres RPCs (one
network round trip, one transaction) — this module never does a
check-then-write across two separate .execute() calls for anything that
affects the canonical allocation.
"""

import logging
import os

from main import supabase
from xera.payments.paystack_provider import PaystackHashrateProvider, new_reference
from xera.payments.crypto_provider import CryptoHashrateProvider, crypto_payments_enabled
from xera.payments.base import PaymentProviderError


logger = logging.getLogger(__name__)


class HashrateError(Exception):
    """Short machine-readable code; routes_hashrate.py maps these to HTTP responses."""


_PROVIDERS = {
    "PAYSTACK": PaystackHashrateProvider(),
    "CRYPTO": CryptoHashrateProvider(),
}

_RESERVATION_ERROR_MAP = {
    "tier_not_found": "tier_not_found",
    "tier_disabled": "tier_disabled",
    "entitlement_cap_exceeded": "insufficient_mining_allocation",
    "invalid_payment_method": "invalid_payment_method",
    "reference_already_used": "reference_already_used",
    "payment_verification_failed": "payment_verification_failed",
}


def paystack_payments_enabled() -> bool:
    return os.getenv("XERA_HASHRATE_PAYMENTS_ENABLED", "false").strip().lower() == "true"


def payment_availability() -> dict:
    """Which rails the purchase endpoint will currently accept — lets the UI
    disable Buy instead of letting the person hit a 403."""
    return {"paystack": paystack_payments_enabled(), "crypto": crypto_payments_enabled()}


def _user_email(user_id: int) -> str | None:
    res = supabase.table("users").select("email").eq("id", user_id).limit(1).execute()
    return (res.data[0].get("email") if res.data else None) or None


def get_tiers(include_disabled: bool = False) -> list[dict]:
    q = supabase.table("xera_hashrate_tiers").select("*")
    if not include_disabled:
        q = q.eq("enabled", True)
    return q.order("price").execute().data


def get_entitlement_state() -> dict:
    res = supabase.table("xera_mining_entitlement_state").select("*").eq("id", 1).limit(1).execute()
    if not res.data:
        raise RuntimeError("xera_mining_entitlement_state row missing — run the hashrate migration.")
    state = res.data[0]
    reserved = float(state["reserved_amount"])
    cap = float(state["cap"])
    warning_threshold = float(state["warning_threshold"])
    closure_threshold = float(state["closure_threshold"])
    return {
        "reserved_amount": reserved,
        "cap": cap,
        "remaining": max(cap - reserved, 0),
        "warning_threshold": warning_threshold,
        "closure_threshold": closure_threshold,
        "warning_active": reserved >= warning_threshold,
        "warning_countdown": max(closure_threshold - reserved, 0),
        "free_mining_closed": bool(state["free_mining_closed"]) or reserved >= closure_threshold,
    }


def preview_tier(tier_id: int) -> dict:
    """Used by the purchase UI to show whether a tier's full session can
    currently be supported, before the person taps buy (section 19) —
    purely informational; the RPC re-checks atomically regardless."""
    res = supabase.table("xera_hashrate_tiers").select("*").eq("id", tier_id).limit(1).execute()
    if not res.data:
        raise HashrateError("tier_not_found")
    tier = res.data[0]
    entitlement = float(tier["daily_rate"]) * int(tier["duration_days"])
    state = get_entitlement_state()
    return {
        "tier": tier,
        "maximum_entitlement": entitlement,
        "supportable": entitlement <= state["remaining"] and tier["enabled"],
        "remaining_allocation": state["remaining"],
    }


def purchase(user_id: int, tier_id: int, payment_method: str) -> dict:
    payment_method = payment_method.upper()
    if payment_method == "PAYSTACK" and not paystack_payments_enabled():
        raise HashrateError("hashrate_payments_not_enabled")
    if payment_method not in _PROVIDERS:
        raise HashrateError("invalid_payment_method")
    if payment_method == "CRYPTO" and not crypto_payments_enabled():
        raise HashrateError("crypto_payments_not_yet_configured")

    provider = _PROVIDERS[payment_method]

    # Resolve the customer email up front: failing after the reservation
    # would just park allocation in PENDING_PAYMENT until the sweep runs.
    email = _user_email(user_id) if payment_method == "PAYSTACK" else None
    if payment_method == "PAYSTACK" and not email:
        raise HashrateError("customer_email_required")

    reference = new_reference()

    try:
        res = supabase.rpc("xera_purchase_hashrate", {
            "p_user_id": user_id,
            "p_tier_id": tier_id,
            "p_payment_method": payment_method,
            "p_reference": reference,
        }).execute()
    except Exception as e:
        msg = str(e)
        for code, mapped in _RESERVATION_ERROR_MAP.items():
            if code in msg:
                raise HashrateError(mapped)
        raise

    row = res.data[0] if isinstance(res.data, list) else res.data

    try:
        provider_init = provider.initialize(
            reference=reference,
            amount=row["price"],
            currency=row["currency"],
            user_id=user_id,
            metadata={"session_id": row["session_id"], "tier_id": tier_id},
            email=email,
        )
    except PaymentProviderError:
        # Payment could not even be initialized — release the reservation
        # immediately rather than leaving it parked in PENDING_PAYMENT.
        _release(reference, "FAILED")
        raise

    return {
        "session_id": row["session_id"],
        "payment_id": row["payment_id"],
        "reference": reference,
        "maximum_entitlement": row["maximum_entitlement"],
        "price": row["price"],
        "currency": row["currency"],
        "payment": provider_init,
    }


def _release(reference: str, status: str) -> dict:
    res = supabase.rpc("xera_release_hashrate_reservation", {
        "p_reference": reference,
        "p_status": status,
    }).execute()
    return res.data[0] if isinstance(res.data, list) else res.data


def confirm_payment(reference: str, tx_hash: str | None = None, raw_webhook: dict | None = None, verified_amount_minor: int | None = None, verified_currency: str | None = None) -> dict:
    """Only call this after independently verifying the payment with the
    provider (webhook signature verified + server-side verify() call) —
    never on the strength of a frontend 'payment successful' message."""
    try:
        res = supabase.rpc("xera_confirm_hashrate_payment", {
            "p_reference": reference,
            "p_tx_hash": tx_hash,
            "p_raw_webhook": raw_webhook or {},
            "p_verified_amount_minor": verified_amount_minor,
            "p_verified_currency": verified_currency,
        }).execute()
    except Exception as e:
        msg = str(e)
        # payment_verification_failed = amount/currency Paystack reported
        # doesn't match the payment row. entitlement_cap_exceeded = a LATE
        # payment (reservation already swept) that the pool can no longer back.
        for code in ("payment_not_found", "payment_already_finalized", "tx_hash_already_used", "payment_verification_failed"):
            if code in msg:
                raise HashrateError(code)
        if "entitlement_cap_exceeded" in msg:
            raise HashrateError("late_payment_no_capacity")
        raise
    return res.data[0] if isinstance(res.data, list) else res.data


def fail_payment(reference: str) -> dict:
    return _release(reference, "FAILED")


def expire_payment(reference: str) -> dict:
    return _release(reference, "EXPIRED")


def cancel_payment(reference: str) -> dict:
    return _release(reference, "CANCELLED")


def handle_paystack_webhook(raw_body: bytes, signature_header: str, payload: dict) -> dict:
    from xera.payments.paystack_provider import verify_webhook_signature, is_xera_hashrate_reference

    if not verify_webhook_signature(raw_body, signature_header):
        raise HashrateError("invalid_webhook_signature")

    event = payload.get("event")
    data = payload.get("data", {})
    reference = data.get("reference", "")

    if not is_xera_hashrate_reference(reference):
        # Not a XERA hashrate payment (could be an EVOSDATA event sharing
        # the same Paystack account) — not this module's concern.
        return {"handled": False}

    provider = _PROVIDERS["PAYSTACK"]

    if event == "charge.success":
        # Never trust the webhook body's amount/status alone — re-verify
        # server-side against Paystack's API.
        verified = provider.verify(reference=reference)
        if not verified["confirmed"]:
            raise HashrateError("payment_verification_failed")
        try:
            result = confirm_payment(
                reference,
                tx_hash=verified.get("tx_hash"),
                raw_webhook=payload,
                verified_amount_minor=verified.get("amount_minor"),
                verified_currency=verified.get("currency"),
            )
        except HashrateError as e:
            if str(e) == "late_payment_no_capacity":
                # The customer really paid, but the allocation filled up after
                # their checkout window lapsed. Retrying can't fix that, so ack
                # the webhook (200) and leave a loud trail for a manual refund.
                logger.critical("XERA hashrate: PAID but cannot activate (allocation full) — refund required. reference=%s", reference)
                return {"handled": True, "needs_refund": True}
            raise
        return {"handled": True, "session": result}

    if event in ("charge.failed",):
        result = fail_payment(reference)
        return {"handled": True, "session": result}

    return {"handled": False}



def claim_reward(user_id: int, session_id: int) -> dict:
    try:
        res = supabase.rpc("xera_claim_hashrate_reward", {
            "p_session_id": session_id,
            "p_user_id": user_id,
        }).execute()
    except Exception as e:
        msg = str(e)
        for code in ("session_not_found", "payment_not_confirmed", "invalid_session_status", "not_yet_claimable", "nothing_to_claim", "wallet_not_found", "wallet_not_active", "allocation_exhausted"):
            if code in msg:
                raise HashrateError(code)
        raise
    return res.data[0] if isinstance(res.data, list) else res.data


def reconcile_pending_payments(max_age_minutes: int = 30) -> dict:
    max_age_minutes = max(5, min(int(max_age_minutes), 1440))
    try:
        res = supabase.rpc("xera_expire_stale_hashrate_payments", {"p_age_minutes": max_age_minutes}).execute()
        row = res.data[0] if isinstance(res.data, list) and res.data else res.data
        return row or {"expired_count": 0, "released_amount": 0}
    except Exception:
        return {"expired_count": 0, "released_amount": 0}

def get_session(user_id: int, session_id: int) -> dict:
    res = (
        supabase.table("xera_hashrate_sessions")
        .select("*")
        .eq("id", session_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HashrateError("session_not_found")
    return res.data[0]


def list_sessions(user_id: int) -> list[dict]:
    return (
        supabase.table("xera_hashrate_sessions")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )
