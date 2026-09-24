"""
XERA hashrate user-facing API — mounted in main.py as:

    from xera.routes_hashrate import router as xera_hashrate_router
    app.include_router(xera_hashrate_router, prefix="/api/xera/hashrate", tags=["xera-hashrate"])

Same auth model as xera/routes.py: every route (except the Paystack
webhook, which is authenticated by signature instead) requires a valid
XERA session token.
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from main import supabase, limiter
from xera.user_auth import verify_user_token, XeraTokenInvalid
from xera import hashrate
from xera.hashrate import HashrateError
from xera.payments.base import PaymentProviderError

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
    "crypto_payments_not_yet_configured":(403, "Crypto payment for hashrate isn't available yet — please use Paystack."),
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
