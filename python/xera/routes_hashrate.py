"""
XERA hashrate user-facing API — mounted in main.py as:

    from xera.routes_hashrate import router as xera_hashrate_router
    app.include_router(xera_hashrate_router, prefix="/api/xera/hashrate", tags=["xera-hashrate"])

Same auth model as xera/routes.py: every route (except the Paystack
webhook, which is authenticated by signature instead) requires a valid
XERA session token.
"""

import logging
import re

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from main import supabase, limiter
from xera.user_auth import verify_user_token, XeraTokenInvalid
from xera import hashrate
from xera.hashrate import HashrateError
from xera.payments.base import PaymentProviderError
from services.evosgpt.currency import currency_for_country

logger = logging.getLogger(__name__)
router = APIRouter()


def _current_user_id(request: Request, authorization: str) -> int:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_user_token(token)
    except XeraTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")


_HASHRATE_ERROR_HTTP = {
    "tier_not_found":                    (404, "Hashrate tier not found."),
    "tier_disabled":                     (403, "This hashrate tier is not currently available."),
    "insufficient_mining_allocation":    (409, "Hashrate unavailable — insufficient remaining mining allocation for the full 30-day session."),
    "invalid_payment_method":            (400, "Unsupported payment method."),
    "crypto_payments_not_yet_configured":(403, "USDT payment isn't available yet — please use Paystack."),
    "hashrate_payments_not_enabled":     (403, "Hashrate payments are not enabled in this environment."),
    "reference_already_used":            (409, "Purchase already in progress."),
    "session_not_found":                 (404, "Hashrate session not found."),
    "payment_not_found":                 (404, "Payment not found."),
    "payment_already_finalized":         (409, "This payment has already been finalized."),
    "tx_hash_already_used":              (409, "This transaction has already been used to activate a session."),
    "invalid_webhook_signature":         (401, "Invalid webhook signature."),
    "payment_verification_failed":       (402, "Payment could not be verified."),
    "not_yet_claimable":                 (400, "This hashrate has not accrued a full 24-hour reward yet."),
    "nothing_to_claim":                  (409, "There is no new hashrate reward to claim."),
    "payment_not_confirmed":             (409, "Your hashrate payment has not been confirmed yet."),
    "invalid_session_status":            (409, "This hashrate session is no longer active."),
    "wallet_not_found":                  (404, "Wallet not found."),
    "wallet_not_active":                 (403, "This wallet is suspended."),
    "allocation_exhausted":              (409, "The mining allocation is exhausted."),
    "customer_email_required":           (400, "Add an email address to your account before paying."),
    "late_payment_no_capacity":          (409, "Payment received after the checkout window and the allocation is now full — contact support for a refund."),
}


def _raise_hashrate_error(e: HashrateError):
    status, message = _HASHRATE_ERROR_HTTP.get(str(e), (400, str(e)))
    raise HTTPException(status_code=status, detail=message)


class PurchaseRequest(BaseModel):
    tier_id: int
    payment_method: str  # "PAYSTACK" | "CRYPTO"


@router.get("/tiers")
@limiter.limit("30/minute")
def list_tiers(request: Request):
    return {
        "tiers": hashrate.get_tiers(),
        "entitlement": hashrate.get_entitlement_state(),
        "payments": hashrate.payment_availability(),
    }


@router.get("/currency")
@limiter.limit("30/minute")
def visitor_currency(request: Request, country: str = ""):
    """
    Display currency for hashrate prices (public, no auth). Prices are stored and BILLED in
    GHS; this only tells the frontend which currency to show and the GHS -> local rate.
    `country` (ISO code) comes from the hosting edge when available; otherwise the visitor's
    IP is looked up. Falls back to GHS (rate 1) whenever the country or rate is unknown.
    """
    code = country.strip().upper()
    if not re.match(r"^[A-Z]{2}$", code):
        code = ""
        try:
            from services.evosgpt.core import get_geo_context  # lazy: heavy module, optional
            code = (get_geo_context(request).get("country_code") or "").upper()
        except Exception as exc:
            logger.warning("XERA hashrate currency: geo lookup unavailable (%s)", exc)
    return currency_for_country(code)


@router.get("/tiers/{tier_id}/preview")
@limiter.limit("30/minute")
def preview_tier(tier_id: int, request: Request):
    try:
        return hashrate.preview_tier(tier_id)
    except HashrateError as e:
        _raise_hashrate_error(e)


@router.post("/purchase")
@limiter.limit("10/minute")
def purchase_hashrate(body: PurchaseRequest, request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    try:
        return hashrate.purchase(user_id, body.tier_id, body.payment_method)
    except HashrateError as e:
        _raise_hashrate_error(e)
    except PaymentProviderError as e:
        # Log the provider's detail server-side; don't leak raw provider
        # messages (or internal codes) to the browser.
        logger.error("XERA hashrate payment provider error for user %s: %s", user_id, e)
        raise HTTPException(status_code=502, detail="Payment provider is unavailable right now. Please try again shortly.")


@router.get("/sessions")
@limiter.limit("30/minute")
def my_sessions(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    hashrate.reconcile_pending_payments()
    return {"sessions": hashrate.list_sessions(user_id)}


@router.get("/sessions/{session_id}")
@limiter.limit("30/minute")
def session_status(session_id: int, request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    try:
        hashrate.reconcile_pending_payments()
        return hashrate.get_session(user_id, session_id)
    except HashrateError as e:
        _raise_hashrate_error(e)


@router.post("/sessions/{session_id}/claim")
@limiter.limit("10/minute")
def claim_hashrate(session_id: int, request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    try:
        return hashrate.claim_reward(user_id, session_id)
    except HashrateError as e:
        _raise_hashrate_error(e)


@router.post("/webhooks/paystack", include_in_schema=False)
@limiter.limit("60/minute")
async def paystack_webhook(request: Request, x_paystack_signature: str = Header(default="")):
    raw_body = await request.body()
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    # One Paystack account/webhook URL serves hashrate AND the one-time transfer fee: route by reference.
    from xera import readiness
    if readiness.is_fee_reference((payload.get("data") or {}).get("reference", "")):
        try:
            result = await run_in_threadpool(readiness.handle_fee_webhook, raw_body, x_paystack_signature, payload)
        except readiness.ReadinessError as e:
            if str(e) == "fee_amount_mismatch":
                return {"ok": True, "handled": False}   # logged CRITICAL for manual review; retrying cannot fix it
            status = 401 if str(e) == "invalid_webhook_signature" else 400
            raise HTTPException(status_code=status, detail=str(e))
        return {"ok": True, **result}

    try:
        # handle_paystack_webhook makes blocking HTTP (Paystack verify) and DB
        # calls; run it in the threadpool so a slow Paystack response can't
        # stall every other request on the event loop.
        result = await run_in_threadpool(hashrate.handle_paystack_webhook, raw_body, x_paystack_signature, payload)
    except HashrateError as e:
        # Paystack retries on non-2xx, which is what we want for a
        # transient/verification failure — but an invalid signature should
        # never be retried into success, so it's still a clear 401.
        status, message = _HASHRATE_ERROR_HTTP.get(str(e), (400, str(e)))
        raise HTTPException(status_code=status, detail=message)

    return {"ok": True, **result}


@router.post("/webhooks/nowpayments", include_in_schema=False)
@limiter.limit("120/minute")
async def nowpayments_webhook(request: Request, x_nowpayments_sig: str = Header(default="")):
    """
    NOWPayments IPN for BOTH hashrate purchases and the one-time transfer fee, routed by
    order_id prefix. Authenticated by HMAC signature; money is then re-verified against
    NOWPayments' API before anything is credited.
    """
    from xera import readiness
    from xera.payments import nowpayments_provider as np

    raw_body = await request.body()
    try:
        signature_ok = np.verify_ipn_signature(raw_body, x_nowpayments_sig)
    except PaymentProviderError:
        # IPN secret not configured: fail closed.
        raise HTTPException(status_code=503, detail="Crypto payments are not configured.")
    if not signature_ok:
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    order_id = payload.get("order_id") or ""
    try:
        if readiness.is_fee_reference(order_id):
            result = await run_in_threadpool(readiness.handle_fee_ipn, payload)
        else:
            result = await run_in_threadpool(hashrate.handle_nowpayments_ipn, payload)
    except readiness.ReadinessError as e:
        if str(e) == "fee_amount_mismatch":
            return {"ok": True, "handled": False}   # logged CRITICAL for manual review; retrying cannot fix it
        raise HTTPException(status_code=400, detail=str(e))
    except HashrateError as e:
        status, message = _HASHRATE_ERROR_HTTP.get(str(e), (400, str(e)))
        raise HTTPException(status_code=status, detail=message)
    except PaymentProviderError as e:
        # NOWPayments' API was unreachable: 502 makes them retry the IPN later.
        logger.error("XERA NOWPayments IPN verify failed: %s", e)
        raise HTTPException(status_code=502, detail="Could not verify the payment right now.")
    return {"ok": True, **result}
