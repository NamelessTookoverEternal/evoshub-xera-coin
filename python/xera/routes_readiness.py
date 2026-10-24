"""
XERA first-transfer readiness API: KYC status/submission, the one-time fee, notifications,
and the admin KYC review queue.

User routes (mounted at /api/xera) - all require the user's XERA token and only ever read or
write the caller's OWN data. None of them accepts a status from the browser.
Admin routes (mounted at /api/admin/xera/kyc) - require an active admin agent, re-checked live.
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from main import supabase, limiter
from xera import readiness
from xera.admin_auth import AdminTokenInvalid, require_active_admin
from xera.user_auth import XeraTokenInvalid, verify_user_token

logger = logging.getLogger(__name__)
router = APIRouter()
admin_router = APIRouter(include_in_schema=False)


def _user_id(authorization: str) -> int:
    try:
        return verify_user_token(authorization.removeprefix("Bearer ").strip())
    except XeraTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")


def _admin_id(authorization: str) -> int:
    try:
        return require_active_admin(supabase, authorization)
    except AdminTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access has been revoked.")


_ERRORS = {
    "kyc_details_invalid":        (400, "Please fill in every field (name, country, ID type and the last digits of your ID)."),
    "kyc_already_verified":       (409, "Your identity is already verified."),
    "kyc_already_pending":        (409, "Your verification is already waiting for review."),
    "kyc_not_found":              (404, "No verification request found for that user."),
    "invalid_decision":           (400, "Decision must be VERIFIED, FAILED or MORE_INFO."),
    "invalid_status":             (400, "Unknown status."),
    "note_required":              (400, "Add a short note for the user when failing or asking for more information."),
    "fee_collection_disabled":    (503, "The processing fee isn't open for payment yet."),
    "fee_already_paid":           (409, "Your processing fee is already paid."),
    "fee_not_configured":         (503, "The processing fee isn't configured yet."),
    "customer_email_required":    (400, "Add an email address to your account before paying."),
    "payments_unavailable":       (503, "Payments are temporarily unavailable. Please try again shortly."),
    "payment_init_failed":        (502, "We couldn't start the payment. Nothing was charged."),
    "fee_payment_not_found":      (404, "Payment not found."),
    "fee_amount_mismatch":        (409, "The confirmed payment did not match the expected fee, so it was not applied. Contact support."),
    "invalid_webhook_signature":  (401, "Invalid webhook signature."),
}


def _http(e: readiness.ReadinessError) -> HTTPException:
    status, message = _ERRORS.get(str(e), (400, "Request could not be completed."))
    return HTTPException(status_code=status, detail=message)


# ---------------------------------------------------------------- user
@router.get("/readiness")
@limiter.limit("60/minute")
def get_readiness(request: Request, authorization: str = Header(default="")):
    """Server-confirmed KYC + fee status for the dashboard cards. Read-only."""
    return {"status": "ok", **readiness.readiness_overview(_user_id(authorization))}


class KycSubmitRequest(BaseModel):
    legal_name: str = Field(..., min_length=3, max_length=120)
    country: str = Field(..., min_length=2, max_length=60)
    id_type: str = Field(..., min_length=2, max_length=40)
    id_last4: str = Field(..., min_length=3, max_length=40)


@router.post("/kyc/submit")
@limiter.limit("5/minute")
def kyc_submit(request: Request, data: KycSubmitRequest, authorization: str = Header(default="")):
    user_id = _user_id(authorization)
    try:
        kyc = readiness.submit_kyc(user_id, legal_name=data.legal_name, country=data.country,
                                   id_type=data.id_type, id_last4=data.id_last4)
    except readiness.ReadinessError as e:
        raise _http(e)
    return {"status": "ok", "kyc": kyc}


@router.post("/fee/checkout")
@limiter.limit("5/minute")
def fee_checkout(request: Request, authorization: str = Header(default="")):
    user_id = _user_id(authorization)
    try:
        return {"status": "ok", **readiness.start_fee_payment(user_id)}
    except readiness.ReadinessError as e:
        raise _http(e)


@router.get("/fee/verify")
@limiter.limit("20/minute")
def fee_verify(request: Request, reference: str = "", authorization: str = Header(default="")):
    """
    Called when the user returns from checkout. The reference only tells us WHICH payment to
    re-check: the result comes from Paystack's API, never from the redirect. A reference that
    belongs to another user is treated as not found.
    """
    user_id = _user_id(authorization)
    if not readiness.is_fee_reference(reference):
        raise HTTPException(status_code=404, detail="Payment not found.")
    owned = supabase.table("xera_fee_payments").select("user_id").eq("reference", reference).limit(1).execute().data
    if not owned or owned[0]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Payment not found.")
    try:
        readiness.apply_verified_fee_payment(reference)
    except readiness.ReadinessError as e:
        raise _http(e)
    return {"status": "ok", "fee": readiness.fee_status(user_id)}


@router.get("/notifications")
@limiter.limit("60/minute")
def get_notifications(request: Request, authorization: str = Header(default="")):
    return {"status": "ok", "notifications": readiness.list_notifications(_user_id(authorization))}


@router.post("/notifications/read")
@limiter.limit("30/minute")
def read_notifications(request: Request, authorization: str = Header(default="")):
    readiness.mark_notifications_read(_user_id(authorization))
    return {"status": "ok"}


# ---------------------------------------------------------------- admin KYC review
@admin_router.get("")
@limiter.limit("60/minute")
def admin_kyc_list(request: Request, status: str = "PENDING", authorization: str = Header(default="")):
    _admin_id(authorization)
    try:
        return {"status": "ok", "items": readiness.list_kyc_for_review(status)}
    except readiness.ReadinessError as e:
        raise _http(e)


class KycReviewRequest(BaseModel):
    decision: str = Field(..., pattern="^(VERIFIED|FAILED|MORE_INFO|verified|failed|more_info)$")
    note: str = Field(default="", max_length=300)


@admin_router.post("/{user_id}/review")
@limiter.limit("60/minute")
def admin_kyc_review(request: Request, user_id: int, data: KycReviewRequest, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    try:
        kyc = readiness.review_kyc(admin_id, user_id, data.decision, data.note)
    except readiness.ReadinessError as e:
        raise _http(e)
    return {"status": "ok", "kyc": kyc}
