"""
Product switches — mounted in main.py as:

    app.include_router(products_router,       prefix="/api/products", tags=["products"])
    app.include_router(products_admin_router, prefix="/api/admin/products")

  GET   /api/products/status        public — {key: {enabled, message}} for greying tiles (cached ~30s by browsers)
  GET   /api/admin/products         admin  — every product with its mode, who changed it and when
  PATCH /api/admin/products/{key}   admin  — {enabled?, enforce?, message?}; every change is audited

Who may flip a switch: any ACTIVE admin agent, checked per request (token + live admin_agents.is_active).
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from main import limiter, supabase
from utils import product_switches as ps
from xera.admin_auth import AdminTokenInvalid, require_active_admin

logger = logging.getLogger(__name__)
router = APIRouter()
admin_router = APIRouter(include_in_schema=False)


def _admin(authorization: str) -> int:
    try:
        return require_active_admin(supabase, authorization)
    except AdminTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access has been revoked.")


@router.get("/status")
@limiter.limit("120/minute")
async def public_status(request: Request, response: Response):
    snap = await run_in_threadpool(ps.snapshot)
    response.headers["Cache-Control"] = "public, max-age=30"
    return {"status": "ok", "products": {k: {"enabled": v["enabled"], "message": v["message"]} for k, v in snap.items()}}


def _admin_view() -> list:
    snap = ps.snapshot(force=True)
    meta = {r["product_key"]: r for r in (supabase.table("product_switches").select("*").execute().data or [])}
    out = []
    for key, v in snap.items():
        row = meta.get(key, {})
        out.append({
            "key": key, "label": v["label"], "enabled": v["enabled"], "enforce": v["enforce"], "message": v["message"],
            "sensitive": key in ps.SENSITIVE,
            "updated_by": row.get("updated_by"), "updated_at": row.get("updated_at"),
        })
    return out


@admin_router.get("")
@limiter.limit("60/minute")
async def admin_list(request: Request, authorization: str = Header(default="")):
    await run_in_threadpool(_admin, authorization)
    return {"status": "ok", "products": await run_in_threadpool(_admin_view)}


class SwitchPatch(BaseModel):
    enabled: bool | None = None
    enforce: bool | None = None
    message: str | None = Field(default=None, max_length=200)
    confirm: bool = False   # required to switch a sensitive product (XERA) off


def _patch(admin_id: int, key: str, data: SwitchPatch) -> dict:
    if key not in ps.PRODUCTS:
        raise HTTPException(status_code=404, detail="Unknown product.")
    if data.enabled is None and data.enforce is None and data.message is None:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    if data.enabled is False and key in ps.SENSITIVE and not data.confirm:
        raise HTTPException(status_code=409, detail=f"{ps.PRODUCTS[key][0]} affects balances and mining. Confirm to switch it off.")
    old = ps.snapshot(force=True)[key]
    new = dict(old)
    if data.enabled is not None:
        new["enabled"] = data.enabled
    if data.enforce is not None:
        new["enforce"] = data.enforce
    if data.message is not None:
        new["message"] = " ".join(data.message.split()) or None
    row = {
        "product_key": key, "label": ps.PRODUCTS[key][0], "enabled": new["enabled"], "enforce": new["enforce"],
        "message": new["message"], "updated_by": admin_id, "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase.table("product_switches").upsert(row, on_conflict="product_key").execute()
    ps.clear_cache()
    try:
        supabase.table("xera_admin_actions").insert({
            "admin_id": admin_id, "action": "PRODUCT_SWITCH_CHANGED",
            "old_value": {"product": key, **{k: old[k] for k in ("enabled", "enforce", "message")}},
            "new_value": {"product": key, **{k: new[k] for k in ("enabled", "enforce", "message")}},
            "reason": None,
        }).execute()
    except Exception:
        logger.exception("product_switches: audit log write failed for %s", key)
    return {"status": "ok", "product": next(p for p in _admin_view() if p["key"] == key)}


@admin_router.patch("/{key}")
@limiter.limit("60/hour")
async def admin_patch(request: Request, key: str, data: SwitchPatch, authorization: str = Header(default="")):
    admin_id = await run_in_threadpool(_admin, authorization)
    return await run_in_threadpool(_patch, admin_id, key, data)
