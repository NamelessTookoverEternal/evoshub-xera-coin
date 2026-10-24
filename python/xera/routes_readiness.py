"""
Readiness routes — mounted in main.py as:

    app.include_router(xera_readiness_router,       prefix="/api/xera",       tags=["xera-readiness"])
    app.include_router(xera_admin_readiness_router, prefix="/api/admin/xera", tags=["xera-admin-kyc"])

User routes take the user id ONLY from the session token. Nothing in a request body
can name another user or set a status. The admin routes need a valid admin token AND a
live active admin_agents row (checked on every call), and write xera_admin_actions.
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from main import supabase, limiter
from xera.user_auth import verify_user_token, XeraTokenInvalid
from xera.admin_auth import AdminTokenInvalid, require_active_admin
from xera import readiness

logger = logging.getLogger(__name__)
router = APIRouter()
admin_router = APIRouter(include_in_schema=False)

_KYC_ERROR_HTTP = {
    "invalid_name":           (400, "Enter your full legal name."),
    "invalid_country":        (400, "Enter your country."),
    "invalid_id_type":        (400, "Choose a valid ID type."),
    "invalid_id_number":      (400, "Enter your ID number."),
    "kyc_unavailable":        (503, "Verification is temporarily unavailable. Please try again later."),
    "kyc_already_pending":    (409, "Your verification is already being reviewed."),
    "kyc_already_verified":   (409, "You are already verified."),
    "invalid_decision":       (400, "Decision must be VERIFIED, FAILED or INFO_REQUIRED."),
    "cannot_review_own_kyc":  (403, "You cannot review your own verification."),
    "kyc_not_found":          (404, "No verification request found for that user."),
    "kyc_not_pending":        (409, "That request is not waiting for review."),
    "note_required":          (400, "A note is required when rejecting or asking for more information."),
}


def _current_user_id(authorization: str) -> int:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_user_token(token)
    except XeraTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")


def _admin_id(authorization: str) -> int:
    try:
        return require_active_admin(supabase, authorization)
    except AdminTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access has been revoked.")


@router.get("/readiness")
@limiter.limit("30/minute")
def get_readiness(request: Request, authorization: str = Header(default="")):
    """Server-confirmed KYC, fee status, missing first-transfer requirements and notifications."""
    user_id = _current_user_id(authorization)
    return {"status": "ok", **readiness.readiness_summary(user_id)}


class KycSubmitRequest(BaseModel):
    # Deliberately NO status field: a client can submit details, never a result.
    legal_name: str = Field(..., min_length=3, max_length=120)
    country: str = Field(..., min_length=2, max_length=56)
    id_type: str = Field(..., max_length=32)
    id_number: str = Field(..., min_length=4, max_length=64)

    model_config = {"extra": "forbid"}


@router.post("/kyc/submit")
@limiter.limit("5/minute")
def kyc_submit(request: Request, data: KycSubmitRequest, authorization: str = Header(default="")):
    user_id = _current_user_id(authorization)
    try:
        result = readiness.submit_kyc(user_id, data.legal_name, data.country, data.id_type, data.id_number)
    except readiness.KycError as e:
        status, message = _KYC_ERROR_HTTP.get(str(e), (400, "Could not submit verification."))
        raise HTTPException(status_code=status, detail=message)
    return {"status": "ok", "kyc": result}


# ------------------------------------------------------------ admin review

@admin_router.get("/kyc/pending")
@limiter.limit("30/minute")
def kyc_pending(request: Request, authorization: str = Header(default="")):
    _admin_id(authorization)
    return {"status": "ok", "pending": readiness.list_pending_kyc()}


class KycReviewRequest(BaseModel):
    decision: str = Field(..., pattern="^(VERIFIED|FAILED|INFO_REQUIRED)$")
    note: str = Field(default="", max_length=500)

    model_config = {"extra": "forbid"}


@admin_router.post("/kyc/{user_id}/review")
@limiter.limit("30/minute")
def kyc_review(request: Request, user_id: int, data: KycReviewRequest, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    try:
        result = readiness.review_kyc(admin_id, user_id, data.decision, data.note)
    except readiness.KycError as e:
        status, message = _KYC_ERROR_HTTP.get(str(e), (400, "Could not record the review."))
        raise HTTPException(status_code=status, detail=message)
    try:
        supabase.table("xera_admin_actions").insert({
            "admin_id": admin_id, "action": "kyc_review", "old_value": None,
            "new_value": {"user_id": user_id, "decision": data.decision}, "reason": data.note or None,
        }).execute()
    except Exception as exc:
        logger.error("XERA KYC REVIEW AUDIT FAILED: %s", exc)
    return {"status": "ok", "kyc": result}
