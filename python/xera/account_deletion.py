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
  POST /preview  step 1: check the password and blockers, return every product's wallet and balance (schedules nothing)
                 A stuck EVOS Data order/withdrawal blocks only the FIRST press (409, code evosdata_in_progress, can_continue);
                 the app then sends continue_busy=true on the second press and popup 2 opens.
  POST /request  step 2: schedule deletion (password required; balances must be acknowledged if any exist)
  POST /cancel   cancel a scheduled deletion
  POST /sweep    finish due requests (X-Cron-Key header; 404 if no key is configured)
"""

import hmac
import logging
import os
from decimal import Decimal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
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
    "evosdata_in_progress": (409, "You have an EVOS Data order or withdrawal in progress. Wait until it finishes, then try again."),
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


_GPT_BUCKETS = ("evosgpt-images", "evosgpt-documents")


def _erase_evosgpt_files(user_id: int) -> int:
    """Delete the user's generated images/documents (public buckets, folder = user id). Returns files removed."""
    removed = 0
    for bucket in _GPT_BUCKETS:
        try:
            store = supabase.storage.from_(bucket)
            names = [f["name"] for f in (store.list(str(user_id)) or []) if f.get("name")]
            if names:
                store.remove([f"{user_id}/{n}" for n in names])
                removed += len(names)
        except Exception as exc:
            logger.critical("ACCOUNT DELETION: could not erase %s files of user %s: %s", bucket, user_id, type(exc).__name__)
    return removed


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
            _erase_evosgpt_files(uid)
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
    acknowledge_loss: bool = False        # the user saw the balances and accepted losing them (second warning)
    seen_xera: str | None = Field(default=None, max_length=40)   # balances shown in the popup; a change = review again
    seen_ghs: str | None = Field(default=None, max_length=40)
    continue_busy: bool = False           # the user saw the "order/withdrawal in progress" notice and pressed Delete again


class PreviewDeletion(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    continue_busy: bool = False           # second press: ignore a stuck EVOS Data order/withdrawal (nothing else)


def _check_password(request: Request, user_id: int, password: str) -> None:
    row = supabase.table("users").select("password").eq("id", user_id).limit(1).execute().data
    try:
        ok = bool(row and row[0].get("password") and pwd_context.verify(password, row[0]["password"]))
    except Exception:
        ok = False
    if not ok:
        _log_security_event(user_id, "ACCOUNT_DELETION_BAD_PASSWORD", request, {})
        raise HTTPException(status_code=403, detail="That password is not correct.")


def _balances(user_id: int) -> dict:
    """Everything the user would lose, from the database (one read)."""
    try:
        raw = supabase.rpc("xera_deletion_preview", {"p_user_id": user_id}).execute().data
    except Exception as exc:
        logger.error("Deletion preview failed for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Could not check your wallets right now. Please try again.")
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    raw = raw if isinstance(raw, dict) else {}
    return {
        "xera": _dec(raw.get("xera_balance")),
        "customer_ghs": _dec(raw.get("customer_wallet_ghs")),
        "agent_ghs": _dec(raw.get("agent_wallet_ghs")),
        "is_agent": bool(raw.get("is_agent")),
        "tier": raw.get("evosgpt_tier"),
    }


def _blocker_rpc(user_id: int, skip_busy: bool = False):
    """The first blocker that applies, or None. skip_busy ignores ONLY a stuck EVOS Data order/withdrawal."""
    if skip_busy:
        try:
            return supabase.rpc("xera_deletion_blocker_v3", {"p_user_id": user_id, "p_skip_busy": True}).execute().data
        except Exception:
            pass                          # migration v3 not run yet: behave like before (the stuck order blocks)
    return supabase.rpc("xera_deletion_blocker", {"p_user_id": user_id}).execute().data


def _blocker_for(user_id: int, skip_busy: bool = False) -> str | None:
    try:
        b = _blocker_rpc(user_id, skip_busy)
    except Exception:
        return None
    return b if isinstance(b, str) else None


def _evosdata_busy(user_id: int) -> bool:
    try:
        return bool(supabase.rpc("xera_deletion_evosdata_busy", {"p_user_id": user_id}).execute().data)
    except Exception:
        return False


def _build_preview(user_id: int) -> dict:
    b = _balances(user_id)
    ghs = b["customer_ghs"] + b["agent_ghs"]
    evosdata_wallets = [{"label": "Customer wallet", "amount": str(b["customer_ghs"]), "unit": "GHS", "lost": b["customer_ghs"] > 0}]
    if b["is_agent"]:
        evosdata_wallets.append({"label": "Agent wallet", "amount": str(b["agent_ghs"]), "unit": "GHS", "lost": b["agent_ghs"] > 0})
    paid_plan = bool(b["tier"]) and str(b["tier"]).strip().lower() not in ("", "basic")
    return {
        "status": "ok",
        "products": [
            {"key": "xera", "name": "XERA",
             "wallets": [{"label": "Pure XERA balance", "amount": str(b["xera"]), "unit": "XERA", "lost": b["xera"] > 0}],
             "notes": ["Your KYC details and ID photos are erased.", "XERA you already claimed to your own wallet stays yours."]},
            {"key": "evosdata", "name": "EVOS Data", "wallets": evosdata_wallets,
             "notes": ["Your past orders stay as anonymous records.", "Your saved personal details are erased."]},
            {"key": "evosgpt", "name": "EVOSGPT", "wallets": [],
             "notes": ([f"Your {b['tier']} plan ends with the account."] if paid_plan else [])
                      + ["Your chat history, memory and generated images and documents are erased.",
                         "No wallet here. The shared learning (which holds no personal information) stays."]},
        ],
        "totals": {"xera": str(b["xera"]), "ghs": str(ghs)},
        "has_balance": b["xera"] > 0 or ghs > 0,
    }


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
            blocker = _blocker_rpc(user_id, True)        # a stuck order is handled by the two-press flow, not by a dead button
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


@router.post("/preview")
@limiter.limit("10/minute")
def preview_deletion(request: Request, data: PreviewDeletion, authorization: str = Header(default="")):
    """Step 1 of 2. Checks the password and every blocker, then lists each product's wallet and balance.
    Schedules nothing: the account is untouched until /request is called."""
    user_id = _current_user_id(request, authorization)
    _check_password(request, user_id, data.password)
    cfg = (supabase.table("xera_account_deletion_config").select("enabled,grace_days").eq("id", 1).limit(1).execute().data or [{}])[0]
    if not bool(cfg.get("enabled", True)):
        raise HTTPException(status_code=403, detail=_BLOCKERS["deletion_disabled"][1])
    if _pending(user_id):
        raise HTTPException(status_code=409, detail="Your deletion is already scheduled.")
    blocker = _blocker_for(user_id, data.continue_busy)
    if blocker == "evosdata_in_progress":
        # First press: tell them once. The app asks again with continue_busy=true if they press Delete again.
        return JSONResponse(status_code=409, content={"detail": _BLOCKERS[blocker][1], "code": blocker, "can_continue": True})
    if blocker in _BLOCKERS:
        raise HTTPException(status_code=_BLOCKERS[blocker][0], detail=_BLOCKERS[blocker][1])
    out = _build_preview(user_id)
    out["grace_days"] = int(cfg.get("grace_days") or 7)
    out["warnings"] = []
    if data.continue_busy and _evosdata_busy(user_id):
        out["warnings"].append("You have an EVOS Data order or withdrawal that is still in progress. It stays on record and will not stop "
                               "your deletion, but once the account is deleted you can no longer follow it up.")
    return out


def _schedule(user_id: int, skip_busy: bool) -> None:
    if skip_busy:
        try:
            supabase.rpc("xera_request_account_deletion_v3", {"p_user_id": user_id, "p_skip_busy": True}).execute()
            return
        except Exception as e:
            if "PGRST202" not in str(e) and "could not find" not in str(e).lower():
                raise
            # migration v3 not run yet: fall through to the old function (a stuck order will then block, with a clear message)
    supabase.rpc("xera_request_account_deletion", {"p_user_id": user_id}).execute()


@router.post("/request")
@limiter.limit("5/minute")
def request_deletion(request: Request, data: RequestDeletion, authorization: str = Header(default="")):
    """Step 2 of 2 (Proceed to delete). Schedules the deletion for grace_days later."""
    user_id = _current_user_id(request, authorization)
    _check_password(request, user_id, data.password)
    if not _pending(user_id):
        current = _build_preview(user_id)
        if data.seen_xera is not None and data.seen_ghs is not None and (
                _dec(data.seen_xera) != _dec(current["totals"]["xera"]) or _dec(data.seen_ghs) != _dec(current["totals"]["ghs"])):
            raise HTTPException(status_code=412, detail="Your balances changed. Please review them again before deleting.")
        if current["has_balance"] and not data.acknowledge_loss:
            raise HTTPException(status_code=409, detail="Please confirm that you understand your remaining balances will be lost.")
    try:
        _schedule(user_id, data.continue_busy)
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
