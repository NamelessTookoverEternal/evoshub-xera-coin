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
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from main import supabase, limiter
from xera import ipcheck
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
