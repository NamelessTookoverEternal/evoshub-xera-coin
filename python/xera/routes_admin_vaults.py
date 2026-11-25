"""
Admin "Vaults" overview. Mounted in main.py as:

    from xera.routes_admin_vaults import router as xera_admin_vaults_router
    app.include_router(xera_admin_vaults_router, prefix="/api/admin/xera/vaults", tags=["xera-admin-vaults"])

Look-only and read-only. Every vault is a total worked out from the ledger; nothing here moves XERA.
To add a vault later: add one entry in _vaults() and one detail route below.

  GET /               every vault with its balance, plus the combined total
  GET /p2p-fees       recent P2P transfers that paid a fee (who paid, who received)
(The discount vault's own activity list is the existing GET /api/admin/xera/vault.)
"""

import logging
from decimal import Decimal

from fastapi import APIRouter, Header, Request

from main import supabase, limiter
from xera.routes_admin import _require_admin

logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)


def _num(v) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal(0)


def _vaults() -> list[dict]:
    out = []
    disc = supabase.rpc("xera_discount_vault_summary", {}).execute().data or {}
    out.append({
        "id": "discount",
        "label": "Discount vault",
        "description": "XERA customers spent on discounts, after refunds.",
        "balance": str(_num(disc.get("balance"))),
        "last_30_days": str(_num(disc.get("last_30_days"))),
        "count": int(disc.get("orders") or 0),
        "count_label": "orders",
    })
    p2p = supabase.rpc("xera_p2p_fee_vault_summary", {}).execute().data or {}
    out.append({
        "id": "p2p",
        "label": "P2P fee vault",
        "description": "Fees paid on top of transfers between XERA users.",
        "balance": str(_num(p2p.get("total_fees"))),
        "last_30_days": str(_num(p2p.get("fees_last_30d"))),
        "count": int(p2p.get("transfers_with_fee") or 0),
        "count_label": "transfers with a fee",
    })
    try:
        nc = supabase.rpc("xera_name_change_fee_summary", {}).execute().data or {}
        out.append({
            "id": "name_change",
            "label": "Name change vault",
            "description": "Fees paid to correct a name.",
            "balance": str(_num(nc.get("total_fees"))),
            "last_30_days": str(_num(nc.get("fees_last_30d"))),
            "count": int(nc.get("changes") or 0),
            "count_label": "name changes",
        })
    except Exception as exc:   # migration not run yet: don't break the Vaults tab
        logger.warning("name change vault unavailable: %s", exc)
    return out


@router.get("")
@limiter.limit("60/minute")
def vaults_overview(request: Request, authorization: str = Header(default="")):
    _require_admin(request, authorization)
    vaults = _vaults()
    total = sum((_num(v["balance"]) for v in vaults), Decimal(0))
    return {"status": "ok", "total": str(total), "vaults": vaults}


@router.get("/p2p-fees")
@limiter.limit("60/minute")
def vault_p2p_fees(request: Request, authorization: str = Header(default=""), limit: int = 50, offset: int = 0):
    _require_admin(request, authorization)
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    rows = (
        supabase.table("xera_p2p_transfers")
        .select("id,created_at,sender_user_id,sender_xera_id,recipient_xera_id,amount,fee_amount,sender_verified")
        .gt("fee_amount", 0)
        .order("id", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
        .data
        or []
    )
    return {"status": "ok", "fees": rows}
