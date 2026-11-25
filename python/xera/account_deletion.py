"""
Self-service account deletion with a grace period. Mounted in main.py as:

    from xera.account_deletion import router as xera_account_deletion_router
    app.include_router(xera_account_deletion_router, prefix="/api/xera/account-deletion", tags=["xera-account-deletion"])

How it works (all rules live in Postgres, migration 20261125_xera_account_deletion_v1.sql):
  * POST /request  asks to delete. Needs the account password. The account keeps working for
                   grace_days (default 7) and the user can cancel any time.
  * After the date the account is ANONYMISED (not removed): name, email, phone, password and invite code
    are replaced, the remaining in-app Pure XERA is forfeited, KYC details are erased (ID photos are erased
    here, in storage). Ledger rows and transfers stay without personal data. On-chain XERA is never touched.
  * The sweep that finishes due requests runs (a) after any XERA sign-in, (b) from the admin "run now" route,
    and (c) from POST /sweep when the env var ACCOUNT_DELETION_CRON_KEY is set (for an outside cron).

Routes (all under /api/xera/account-deletion):
  GET  /status   is a deletion scheduled? when? what would be lost? can I start one?
  POST /request  schedule deletion (password required)
  POST /cancel   cancel a scheduled deletion
  POST /sweep    finish due requests (X-Cron-Key header; 404 if no key is configured)
"""

import hmac
import logging
import os
from decimal import Decimal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from main import supabase, limiter
from xera import kyc_documents
from xera.routes import _current_user_id, _log_security_event
from xera.routes_auth import pwd_context

logger = logging.getLogger(__name__)
router = APIRouter()

_BLOCKERS = {
    "deletion_disabled":  (403, "Account deletion is paused right now. Please contact support."),
    "wallet_not_active":  (409, "Your wallet is suspended, so the account can't be deleted. Contact support."),
    "account_locked":     (409, "Your account is under review, so it can't be deleted right now. Contact support."),
    "claim_in_progress":  (409, "You have an on-chain claim in progress. Wait until it finishes, then try again."),
    "order_in_progress":  (409, "You have a data order in progress. Wait until it finishes, then try again."),
    "kyc_in_review":      (409, "Your identity check is under review. Wait for the result, then try again."),
    "user_not_found":     (404, "Account not found."),
    "no_pending_deletion": (404, "No deletion is scheduled for this account."),
}


def _dec(v) -> Decimal:
    try:
        return Decimal(str(v if v is not None else 0))
    except Exception:
        return Decimal(0)


def _rpc_error(msg: str) -> HTTPException | None:
    for code, (status, message) in _BLOCKERS.items():
        if code in msg:
            return HTTPException(status_code=status, detail=message)
    return None


def _pending(user_id: int) -> dict | None:
    rows = (supabase.table("xera_account_deletions").select("id,requested_at,purge_after")
            .eq("user_id", user_id).eq("status", "PENDING").limit(1).execute().data)
    return rows[0] if rows else None


def process_due() -> dict:
    """Finish every request whose date has passed. Safe to call any time, and to call twice."""
    done = waiting = 0
    ids = supabase.rpc("xera_due_account_deletions", {}).execute().data or []
    for uid in ids:
        uid = int(uid["xera_due_account_deletions"] if isinstance(uid, dict) else uid)
        try:
            res = supabase.rpc("xera_complete_account_deletion", {"p_user_id": uid}).execute()
            row = res.data[0] if isinstance(res.data, list) and res.data else res.data
            if not row or (isinstance(row, dict) and not row.get("id")):
                waiting += 1     # a blocker appeared (locked, claim in progress...): tried again next time
                continue
            done += 1
            try:
                stats = kyc_documents.purge_user(uid, "ACCOUNT_DELETED")
                if stats.get("failed"):
                    logger.critical("ACCOUNT DELETION: %s KYC file(s) of user %s could not be erased", stats["failed"], uid)
            except Exception as exc:
                logger.critical("ACCOUNT DELETION: KYC file erase failed for user %s: %s", uid, type(exc).__name__)
        except Exception as exc:
            logger.error("Account deletion failed for user %s: %s", uid, exc)
    return {"completed": done, "waiting": waiting}


def process_due_safely() -> None:
    try:
        process_due()
    except Exception as exc:     # the migration may not be run yet; never break the caller
        logger.warning("account deletion sweep skipped: %s", exc)


class RequestDeletion(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@router.get("/status")
@limiter.limit("30/minute")
def deletion_status(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    cfg = (supabase.table("xera_account_deletion_config").select("enabled,grace_days").eq("id", 1).limit(1).execute().data or [{}])[0]
    wallet = supabase.table("xera_wallets").select("cached_balance").eq("user_id", user_id).limit(1).execute().data
    balance = _dec(wallet[0]["cached_balance"]) if wallet else Decimal(0)
    pending = _pending(user_id)
    blocker = None
    if not pending:
        try:
            blocker = supabase.rpc("xera_deletion_blocker", {"p_user_id": user_id}).execute().data
        except Exception:
            blocker = None
    return {
        "status": "ok",
        "enabled": bool(cfg.get("enabled", True)),
        "grace_days": int(cfg.get("grace_days") or 7),
        "balance": str(balance),
        "pending": bool(pending),
        "purge_after": pending["purge_after"] if pending else None,
        "blocked_reason": blocker if isinstance(blocker, str) else None,
        "blocked_message": _BLOCKERS[blocker][1] if isinstance(blocker, str) and blocker in _BLOCKERS else None,
    }


@router.post("/request")
@limiter.limit("5/minute")
def request_deletion(request: Request, data: RequestDeletion, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    row = supabase.table("users").select("password").eq("id", user_id).limit(1).execute().data
    try:
        ok = bool(row and row[0].get("password") and pwd_context.verify(data.password, row[0]["password"]))
    except Exception:
        ok = False
    if not ok:
        _log_security_event(user_id, "ACCOUNT_DELETION_BAD_PASSWORD", request, {})
        raise HTTPException(status_code=403, detail="That password is not correct.")
    try:
        supabase.rpc("xera_request_account_deletion", {"p_user_id": user_id}).execute()
    except Exception as e:
        err = _rpc_error(str(e))
        if err:
            raise err
        logger.error("Account deletion request failed: %s", e)
        raise HTTPException(status_code=500, detail="Could not schedule deletion. Please try again.")
    _log_security_event(user_id, "ACCOUNT_DELETION_REQUESTED", request, {})
    return deletion_status(request, authorization)


@router.post("/cancel")
@limiter.limit("10/minute")
def cancel_deletion(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    try:
        supabase.rpc("xera_cancel_account_deletion", {"p_user_id": user_id}).execute()
    except Exception as e:
        err = _rpc_error(str(e))
        if err:
            raise err
        logger.error("Account deletion cancel failed: %s", e)
        raise HTTPException(status_code=500, detail="Could not cancel. Please try again.")
    _log_security_event(user_id, "ACCOUNT_DELETION_CANCELLED", request, {})
    return deletion_status(request, authorization)


@router.post("/sweep", include_in_schema=False)
@limiter.limit("10/minute")
def sweep(request: Request, x_cron_key: str = Header(default="")):
    key = os.getenv("ACCOUNT_DELETION_CRON_KEY", "")
    if not key:
        raise HTTPException(status_code=404, detail="Not found.")
    if not hmac.compare_digest(key.encode(), x_cron_key.encode()):
        raise HTTPException(status_code=403, detail="Forbidden.")
    return {"status": "ok", **process_due()}
