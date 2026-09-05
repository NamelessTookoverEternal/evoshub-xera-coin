"""
XERA user-facing API — mounted in main.py as:

    from xera.routes import router as xera_router
    app.include_router(xera_router, prefix="/api/xera", tags=["xera"])

Every route here requires a valid XERA session token (see user_auth.py),
issued by /auth/login. None of these trust a user_id from the request body.
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from main import supabase, limiter
from xera.user_auth import verify_user_token, XeraTokenInvalid
from xera.config import get_config, get_allocations, get_mining_config
from xera.wallet import get_or_create_wallet, get_transactions
from xera.mining import start_session, get_status, claim, current_rate, MiningError
from xera.daily import get_daily_status, claim_daily, DailyClaimError

logger = logging.getLogger(__name__)
router = APIRouter()


def _log_security_event(user_id: int | None, event_type: str, request: Request, details: dict | None = None):
    try:
        supabase.table("xera_security_events").insert({
            "user_id": user_id,
            "event_type": event_type,
            "details": details or {},
            "ip_address": request.client.host if request.client else None,
        }).execute()
    except Exception as e:
        # Logging a security event must never itself break the request.
        logger.error("XERA SECURITY EVENT LOG FAILED: %s", str(e))


def _current_user_id(request: Request, authorization: str) -> int:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_user_token(token)
    except XeraTokenInvalid:
        _log_security_event(None, "UNAUTHORIZED_ACCESS", request, {"path": str(request.url.path)})
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")


_MINING_ERROR_HTTP = {
    "mining_disabled":        (403, "Mining is currently disabled."),
    "active_session_exists":  (409, "You already have an active mining session."),
    "wallet_not_active":      (403, "This wallet is suspended."),
    "session_not_found":      (404, "Mining session not found."),
    "invalid_session_status": (409, "This session has already been claimed or cancelled."),
    "not_yet_expired":        (400, "This mining session hasn't finished yet."),
    "allocation_exhausted":   (409, "The mining allocation for this phase has been fully distributed."),
    "wallet_not_found":       (404, "Wallet not found."),
}


def _raise_mining_error(e: MiningError, request: Request, user_id: int):
    code = str(e)
    status, message = _MINING_ERROR_HTTP.get(code, (400, "Could not process mining request."))
    if code in ("active_session_exists", "invalid_session_status", "not_yet_expired"):
        _log_security_event(user_id, "DUPLICATE_CLAIM_ATTEMPT" if code != "not_yet_expired" else "INVALID_SESSION",
                             request, {"code": code})
    elif code == "allocation_exhausted":
        _log_security_event(user_id, "ALLOCATION_EXCEEDED", request, {"code": code})
    raise HTTPException(status_code=status, detail=message)


# ------------------------------------------------------------
# WALLET
# ------------------------------------------------------------

@router.get("/wallet")
@limiter.limit("30/minute")
def get_wallet(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    wallet = get_or_create_wallet(user_id)
    cfg = get_config()
    return {
        "status": "ok",
        "balance": wallet["cached_balance"],
        "wallet_status": wallet["status"],
        "features": {
            "mining_enabled": cfg["mining_enabled"] and cfg["system_enabled"],
            "sale_enabled": cfg["sale_enabled"],
            "withdrawal_enabled": cfg["withdrawal_enabled"],
            "transfer_enabled": cfg["transfer_enabled"],
        },
    }


@router.get("/transactions")
@limiter.limit("30/minute")
def get_wallet_transactions(request: Request, authorization: str = Header(default=""), limit: int = 50, offset: int = 0):
    user_id = _current_user_id(request, authorization)
    limit = min(max(limit, 1), 100)
    return {"status": "ok", "transactions": get_transactions(user_id, limit, offset)}


# ------------------------------------------------------------
# MINING
# ------------------------------------------------------------

@router.get("/mining/status")
@limiter.limit("60/minute")
def mining_status(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    session = get_status(user_id)
    if not session:
        return {"status": "ok", "mining": None}
    return {"status": "ok", "mining": session}


@router.post("/mining/start")
@limiter.limit("5/minute")
def mining_start(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    try:
        session = start_session(user_id)
    except MiningError as e:
        _raise_mining_error(e, request, user_id)
    return {"status": "ok", "mining": session}


class ClaimRequest(BaseModel):
    session_id: int = Field(..., gt=0)


@router.post("/mining/claim")
@limiter.limit("10/minute")
def mining_claim(request: Request, data: ClaimRequest, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    try:
        result = claim(user_id, data.session_id)
    except MiningError as e:
        _raise_mining_error(e, request, user_id)
    return {"status": "ok", **result}


# ------------------------------------------------------------
# DAILY CLAIM
# ------------------------------------------------------------

_DAILY_ERROR_HTTP = {
    "daily_claim_disabled": (403, "Daily claim is currently disabled."),
    "already_claimed_today": (409, "You've already claimed today's reward."),
    "wallet_not_active":     (403, "This wallet is suspended."),
}


@router.get("/daily/status")
@limiter.limit("30/minute")
def daily_status(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    return {"status": "ok", "daily": get_daily_status(user_id)}


@router.post("/daily/claim")
@limiter.limit("10/minute")
def daily_claim_route(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    try:
        result = claim_daily(user_id)
    except DailyClaimError as e:
        code = str(e)
        status, message = _DAILY_ERROR_HTTP.get(code, (400, "Could not process daily claim."))
        if code == "already_claimed_today":
            _log_security_event(user_id, "DUPLICATE_CLAIM_ATTEMPT", request, {"code": code})
        raise HTTPException(status_code=status, detail=message)
    return {"status": "ok", **result}


# ------------------------------------------------------------
# ECOSYSTEM (public read — admin-curated directory of Evoxera sites)
# ------------------------------------------------------------

@router.get("/ecosystem")
@limiter.limit("60/minute")
def ecosystem_links(request: Request):
    res = (
        supabase.table("xera_ecosystem_links")
        .select("id,name,url,image_url")
        .eq("is_active", True)
        .order("sort_order")
        .execute()
    )
    return {"status": "ok", "links": res.data or []}


# ------------------------------------------------------------
# PUBLIC (no auth — aggregate info only, no per-user data)
# ------------------------------------------------------------

@router.get("/public/stats")
@limiter.limit("60/minute")
def public_stats(request: Request):
    cfg = get_config()
    alloc = get_allocations()
    rate = current_rate() if cfg["mining_enabled"] else None

    # Aggregate counts only — no user ids, emails, or per-account data ever
    # leave this route. count="exact" with no .select() payload columns
    # returns just the row count from Postgres, not the rows themselves.
    registered_res = supabase.table("xera_wallets").select("id", count="exact").execute()
    claimed_sessions_res = (
        supabase.table("xera_mining_sessions").select("id", count="exact").eq("status", "CLAIMED").execute()
    )

    return {
        "status": "ok",
        "current_phase": cfg["current_phase"],
        "initial_target": alloc["total_target"],
        "mining_allocation": alloc["mining_allocation"],
        "mining_distributed": alloc["mining_distributed"],
        "mining_allocation_remaining": float(alloc["mining_allocation"]) - float(alloc["mining_distributed"]),
        "active_miners": rate["active_miners"] if rate else 0,
        "registered_users": registered_res.count or 0,
        "completed_mining_sessions": claimed_sessions_res.count or 0,
        # Mirrors mining_distributed today (mining is the only live reward
        # source XERA can be claimed through) — kept as a distinct field so
        # the public stats page doesn't need to know that detail.
        "total_claimed": alloc["mining_distributed"],
        "mining_enabled": cfg["mining_enabled"] and cfg["system_enabled"],
        "sale_enabled": cfg["sale_enabled"],
        "withdrawal_enabled": cfg["withdrawal_enabled"],
        "transfer_enabled": cfg["transfer_enabled"],
    }


@router.get("/public/tokenomics")
@limiter.limit("30/minute")
def public_tokenomics(request: Request):
    """
    Reads xera_allocations directly — the same row the admin config screen
    edits — so this can never drift from what's actually configured. The
    "cap enforced" flags below describe real CHECK constraints that exist
    in the schema (20260901_xera_token_v1.sql: xera_allocations_sum_within_target
    and xera_mining_distributed_within_allocation), not a marketing claim —
    if those constraints are ever removed from the schema this response
    would need updating to match.
    """
    alloc = get_allocations()
    mining_remaining = float(alloc["mining_allocation"]) - float(alloc["mining_distributed"])
    return {
        "status": "ok",
        "total_target": alloc["total_target"],
        "mining_allocation": alloc["mining_allocation"],
        "mining_distributed": alloc["mining_distributed"],
        "mining_remaining": mining_remaining,
        "sale_allocation": alloc["sale_allocation"],
        "community_allocation": alloc["community_allocation"],
        "liquidity_allocation": alloc["liquidity_allocation"],
        "treasury_allocation": alloc["treasury_allocation"],
        "allocation_sum_capped_at_target": True,
        "mining_distributed_capped_at_allocation": True,
    }


@router.get("/public/mining-info")
@limiter.limit("30/minute")
def public_mining_info(request: Request):
    cfg = get_config()
    mining_cfg = get_mining_config()
    return {
        "status": "ok",
        "mining_enabled": cfg["mining_enabled"] and cfg["system_enabled"],
        "session_hours": mining_cfg["session_hours"],
        "min_reward_per_session": mining_cfg["min_reward_per_session"],
        "max_reward_per_session": mining_cfg["max_reward_per_session"],
    }
