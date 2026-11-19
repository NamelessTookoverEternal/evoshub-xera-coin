"""
Admin review of XERA in-app P2P transfers. Mounted in main.py as:

    from xera.routes_admin_p2p import router as xera_admin_p2p_router
    app.include_router(xera_admin_p2p_router, prefix="/api/admin/xera/p2p", tags=["xera-admin-p2p"])

Same admin gate as every other admin route (live admin_agents check). Read-only except
POST /config, which only edits xera_p2p_config and is written to xera_admin_actions.

  GET  /overview    limits + fee settings, look-only fee total, whether the VPN checker is set up
  GET  /flagged     wallets that received XERA from several unverified accounts or shared IPs
  GET  /transfers   recent transfers with IP, VPN note, sender verified/unverified, fee
  POST /config      change limits, the unverified fee, the unverified daily cap, flag thresholds
  GET  /locks       accounts whose money side (send + withdraw) is locked
  POST /autolock    switch the auto-lock on or off (switching on runs a scan straight away)
  POST /unlock      unlock one account, with a reason and an optional false-flag reward
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from main import supabase, limiter
from xera import ipcheck
from xera import money_lock
from xera.routes_admin import _require_admin, _log_admin_action

logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)


def _cfg() -> dict:
    res = supabase.table("xera_p2p_config").select("*").eq("id", 1).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=503, detail="P2P config row is missing. Run the P2P migrations.")
    return res.data[0]


@router.get("/overview")
@limiter.limit("60/minute")
def p2p_overview(request: Request, authorization: str = Header(default="")):
    _require_admin(request, authorization)
    vault = supabase.rpc("xera_p2p_fee_vault_summary", {}).execute().data or {}
    return {
        "status": "ok",
        "config": _cfg(),
        "fee_vault": vault,
        "ip_check_configured": ipcheck.configured(),
    }


@router.get("/flagged")
@limiter.limit("30/minute")
def p2p_flagged(request: Request, authorization: str = Header(default=""),
                min_senders: int | None = None, days: int | None = None):
    _require_admin(request, authorization)
    args = {}
    if min_senders is not None:
        args["p_min_senders"] = max(2, min(min_senders, 100))
    if days is not None:
        args["p_days"] = max(1, min(days, 90))
    rows = supabase.rpc("xera_p2p_flagged", args).execute().data or []
    return {"status": "ok", "flagged": rows}


@router.get("/transfers")
@limiter.limit("60/minute")
def p2p_transfers(request: Request, authorization: str = Header(default=""),
                  limit: int = 50, offset: int = 0,
                  recipient_xera_id: str | None = None, sender_xera_id: str | None = None):
    _require_admin(request, authorization)
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    q = (supabase.table("xera_p2p_transfers")
         .select("id,created_at,sender_user_id,recipient_user_id,sender_xera_id,recipient_xera_id,"
                 "amount,fee_amount,sender_verified,ip_address,ip_risk"))
    if recipient_xera_id:
        q = q.eq("recipient_xera_id", recipient_xera_id.strip().upper()[:20])
    if sender_xera_id:
        q = q.eq("sender_xera_id", sender_xera_id.strip().upper()[:20])
    rows = q.order("id", desc=True).range(offset, offset + limit - 1).execute().data or []
    return {"status": "ok", "transfers": rows}


class P2PConfigUpdate(BaseModel):
    min_amount: Decimal | None = Field(default=None, gt=0, le=1_000_000)
    max_amount: Decimal | None = Field(default=None, gt=0, le=1_000_000)
    daily_max_total: Decimal | None = Field(default=None, gt=0, le=10_000_000)
    unverified_fee_percent: Decimal | None = Field(default=None, ge=0, le=100)
    verified_fee_percent: Decimal | None = Field(default=None, ge=0, le=100)
    unverified_daily_max: Decimal | None = Field(default=None, gt=0, le=10_000_000)
    flag_min_senders: int | None = Field(default=None, ge=2, le=100)
    flag_window_days: int | None = Field(default=None, ge=1, le=90)
    reason: str = Field(default="", max_length=300)


@router.post("/config")
@limiter.limit("20/minute")
def p2p_update_config(request: Request, data: P2PConfigUpdate, authorization: str = Header(default="")):
    admin_id = _require_admin(request, authorization)
    patch: dict = {}
    for field in ("min_amount", "max_amount", "daily_max_total", "unverified_daily_max"):
        v = getattr(data, field)
        if v is not None:
            patch[field] = str(v)
    if data.unverified_fee_percent is not None:
        patch["unverified_fee_bps"] = int((data.unverified_fee_percent * 100).to_integral_value())
    if data.verified_fee_percent is not None:
        patch["verified_fee_bps"] = int((data.verified_fee_percent * 100).to_integral_value())
    for field in ("flag_min_senders", "flag_window_days"):
        v = getattr(data, field)
        if v is not None:
            patch[field] = v
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to change.")

    old = _cfg()
    try:
        supabase.table("xera_p2p_config").update({**patch, "updated_by": admin_id, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", 1).execute()
    except Exception as e:
        # The database CHECK keeps the numbers consistent (min <= max <= daily caps, etc.).
        logger.info("XERA P2P config rejected: %s", e)
        raise HTTPException(status_code=400, detail="Those numbers don't fit together (min <= max <= unverified daily cap <= daily total).")
    new = _cfg()
    _log_admin_action(admin_id, "P2P_CONFIG_UPDATED", old, new, data.reason or None)
    return {"status": "ok", "config": new}


# ------------------------------------------------------------
# AUTO-LOCK (money side only: send + withdraw). Migration 20261119_xera_p2p_autolock_v4.sql
# ------------------------------------------------------------

@router.get("/locks")
@limiter.limit("60/minute")
def p2p_locks(request: Request, authorization: str = Header(default="")):
    _require_admin(request, authorization)
    try:
        rows = (supabase.table("xera_money_locks")
                .select("user_id,locked_at,lock_source,lock_role,lock_reasons,related_xera_id,lock_count")
                .eq("locked", True).order("locked_at", desc=True).limit(200).execute().data or [])
    except Exception as e:
        if money_lock._table_missing(e):
            raise HTTPException(status_code=503, detail="Auto-lock is not set up yet. Run the v4 migration.")
        raise
    if rows:
        ids = [r["user_id"] for r in rows]
        users = supabase.table("users").select("id,xera_id").in_("id", ids).execute().data or []
        xid = {u["id"]: u.get("xera_id") for u in users}
        for r in rows:
            r["xera_id"] = xid.get(r["user_id"])
    return {"status": "ok", "locks": rows}


class AutoLockSwitch(BaseModel):
    enabled: bool
    reason: str = Field(default="", max_length=300)


@router.post("/autolock")
@limiter.limit("10/minute")
def p2p_autolock_switch(request: Request, data: AutoLockSwitch, authorization: str = Header(default="")):
    admin_id = _require_admin(request, authorization)
    old = _cfg()
    if "auto_lock_enabled" not in old:
        raise HTTPException(status_code=503, detail="Auto-lock is not set up yet. Run the v4 migration.")
    supabase.table("xera_p2p_config").update({
        "auto_lock_enabled": data.enabled, "updated_by": admin_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", 1).execute()
    _log_admin_action(admin_id, "P2P_AUTOLOCK_ON" if data.enabled else "P2P_AUTOLOCK_OFF",
                      {"auto_lock_enabled": old.get("auto_lock_enabled")}, {"auto_lock_enabled": data.enabled},
                      data.reason or None)
    newly = money_lock.run_scan() if data.enabled else []
    return {"status": "ok", "auto_lock_enabled": data.enabled, "newly_locked": len(newly)}


class UnlockRequest(BaseModel):
    user_id: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=300)
    false_flag: bool = False
    reward: Decimal = Field(default=Decimal(0), ge=0, le=100_000)


@router.post("/unlock")
@limiter.limit("20/minute")
def p2p_unlock(request: Request, data: UnlockRequest, authorization: str = Header(default="")):
    admin_id = _require_admin(request, authorization)
    if data.reward > 0 and not data.false_flag:
        raise HTTPException(status_code=400, detail="Tick \"false flag\" to give a reward.")
    if data.reward.as_tuple().exponent < -4:
        raise HTTPException(status_code=400, detail="Reward can have up to 4 decimals.")
    try:
        res = supabase.rpc("xera_money_unlock", {
            "p_user_id": data.user_id, "p_admin_id": admin_id, "p_reason": data.reason,
            "p_false_flag": data.false_flag, "p_reward": str(data.reward),
        }).execute()
    except Exception as e:
        msg = str(e)
        if "not_locked" in msg:
            raise HTTPException(status_code=409, detail="That account is not locked.")
        if "reason_required" in msg:
            raise HTTPException(status_code=400, detail="Give a reason (at least 3 characters).")
        logger.error("XERA money unlock failed: %s", msg)
        raise HTTPException(status_code=500, detail="Could not unlock. Nothing was changed.")
    return {"status": "ok", "result": res.data}
