"""
Paid name change for a signed-in user. Mounted in main.py as:

    from xera.name_change import router as xera_name_change_router
    app.include_router(xera_name_change_router, prefix="/api/xera/name-change", tags=["xera-name-change"])

Rules (all enforced in the Postgres function xera_change_name, migration 20261124_xera_name_change_v1.sql):
  * One paid change per person (admin can grant more), fee set in xera_name_change_config (default 100 Pure XERA).
  * Locked once KYC is VERIFIED or PENDING.
  * The fee comes from spendable Pure XERA and is recorded in the ledger as NAME_CHANGE_FEE.
  * The user is always the one in the session token. This module never writes a balance.
  * An account with its money side locked (xera.money_lock) cannot change its name.

Routes:
  GET  /status   my name, the fee, slots left, and whether I can change it now
  POST /change   change my name (idempotent on request_id)
"""

import logging
import re
from decimal import Decimal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from main import supabase, limiter
from xera import money_lock
from xera.name_rules import check_real_name
from xera.routes import _current_user_id, _log_security_event

logger = logging.getLogger(__name__)
router = APIRouter()

_REQ_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

_ERRORS = [
    ("name_change_disabled", (403, "Name changes are paused right now. Please try again later.")),
    ("kyc_locked",           (403, "Your name is locked because your identity check has started. Contact support if it is wrong.")),
    ("no_change_left",       (409, "You have already used your name change. Contact support for help.")),
    ("same_name",            (400, "That is already your name.")),
    ("insufficient_balance", (402, "You don't have enough Pure XERA for the fee.")),
    ("wallet_not_active",    (403, "Your wallet is suspended.")),
    ("wallet_not_found",     (404, "Wallet not found.")),
    ("user_not_found",       (404, "Account not found.")),
    ("invalid_request",      (400, "Invalid request. Please try again.")),
]


def _dec(v) -> Decimal:
    try:
        return Decimal(str(v if v is not None else 0))
    except Exception:
        return Decimal(0)


def _config() -> dict:
    res = supabase.table("xera_name_change_config").select("*").eq("id", 1).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=503, detail="Name change is being set up. Please try again shortly.")
    return res.data[0]


def _state(user_id: int) -> dict:
    cfg = _config()
    user = supabase.table("users").select("full_name").eq("id", user_id).limit(1).execute().data
    if not user:
        raise HTTPException(status_code=404, detail="Account not found.")
    used = len(supabase.table("xera_name_changes").select("id").eq("user_id", user_id).execute().data or [])
    extra_row = supabase.table("xera_name_change_allowance").select("extra_slots").eq("user_id", user_id).limit(1).execute().data
    allowed = int(cfg.get("max_changes") or 0) + int((extra_row[0]["extra_slots"] if extra_row else 0) or 0)
    kyc = supabase.table("xera_kyc").select("status").eq("user_id", user_id).limit(1).execute().data
    kyc_status = (kyc[0].get("status") if kyc else None) or "UNVERIFIED"
    kyc_locked = kyc_status in ("VERIFIED", "PENDING")
    fee = _dec(cfg.get("fee"))
    try:
        spendable = _dec(supabase.rpc("xera_discount_spendable", {"p_user_id": user_id}).execute().data)
    except Exception:
        spendable = Decimal(0)

    reason = None
    if not cfg.get("enabled"):
        reason = "paused"
    elif kyc_locked:
        reason = "kyc_locked"
    elif used >= allowed:
        reason = "no_change_left"
    elif money_lock.is_locked(user_id):
        reason = "money_locked"
    elif spendable < fee:
        reason = "insufficient_balance"
    return {
        "name": user[0].get("full_name"),
        "fee": str(fee),
        "enabled": bool(cfg.get("enabled")),
        "changes_used": used,
        "changes_allowed": allowed,
        "kyc_locked": kyc_locked,
        "spendable": str(spendable),
        "can_change": reason is None,
        "reason": reason,
    }


class ChangeNameRequest(BaseModel):
    new_name: str = Field(min_length=3, max_length=80)
    request_id: str = Field(min_length=8, max_length=64)


@router.get("/status")
@limiter.limit("30/minute")
def name_change_status(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    return {"status": "ok", **_state(user_id)}


@router.post("/change")
@limiter.limit("5/minute")
def name_change(request: Request, data: ChangeNameRequest, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    if not _REQ_RE.match(data.request_id):
        raise HTTPException(status_code=400, detail="Invalid request. Please try again.")

    clean, err = check_real_name(data.new_name)
    if err:
        raise HTTPException(status_code=400, detail=err)

    if money_lock.is_locked(user_id):
        _log_security_event(user_id, "NAME_CHANGE_REFUSED", request, {"code": "money_locked"})
        raise HTTPException(status_code=403, detail=money_lock.LOCK_MESSAGE)

    try:
        res = supabase.rpc("xera_change_name", {
            "p_user_id": user_id, "p_new_name": clean, "p_request_id": data.request_id,
        }).execute()
    except Exception as e:
        msg = str(e)
        for code, (status, message) in _ERRORS:
            if code in msg:
                if code in ("kyc_locked", "no_change_left"):
                    _log_security_event(user_id, "NAME_CHANGE_REFUSED", request, {"code": code})
                raise HTTPException(status_code=status, detail=message)
        logger.error("XERA name change failed unexpectedly: %s", msg)
        raise HTTPException(status_code=500, detail="Name change failed. You were not charged. Please try again.")

    row = res.data[0] if isinstance(res.data, list) and res.data else (res.data or {})
    _log_security_event(user_id, "NAME_CHANGED", request, {"change_id": row.get("id")})
    return {"status": "ok", **_state(user_id)}
