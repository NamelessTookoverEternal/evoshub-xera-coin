"""
Admin side of the paid name change. Mounted in main.py as:

    from xera.routes_admin_name_change import router as xera_admin_name_change_router
    app.include_router(xera_admin_name_change_router, prefix="/api/admin/xera/name-change", tags=["xera-admin-name-change"])

  GET  /          recent name changes (old name, new name, fee) + total fees
  POST /grant     give one person extra name-change slots (support cases, e.g. a typo)

The fee and the on/off switch live in the xera_name_change_config row:
    UPDATE xera_name_change_config SET fee = 150 WHERE id = 1;
    UPDATE xera_name_change_config SET enabled = false WHERE id = 1;
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from main import supabase, limiter
from xera.routes_admin import _require_admin, _log_admin_action

logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)


@router.get("")
@limiter.limit("60/minute")
def name_changes(request: Request, authorization: str = Header(default=""), limit: int = 50, offset: int = 0,
                 user_id: int | None = None):
    _require_admin(request, authorization)
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    q = supabase.table("xera_name_changes").select("id,created_at,user_id,old_name,new_name,fee_amount")
    if user_id:
        q = q.eq("user_id", user_id)
    rows = q.order("id", desc=True).range(offset, offset + limit - 1).execute().data or []
    summary = supabase.rpc("xera_name_change_fee_summary", {}).execute().data or {}
    return {"status": "ok", "summary": summary, "changes": rows}


class GrantRequest(BaseModel):
    user_id: int = Field(ge=1)
    slots: int = Field(default=1, ge=1, le=5)
    reason: str = Field(min_length=3, max_length=300)


@router.post("/grant")
@limiter.limit("20/minute")
def grant_slots(request: Request, data: GrantRequest, authorization: str = Header(default="")):
    admin_id = _require_admin(request, authorization)
    if not supabase.table("users").select("id").eq("id", data.user_id).limit(1).execute().data:
        raise HTTPException(status_code=404, detail="User not found.")
    cur = supabase.table("xera_name_change_allowance").select("extra_slots").eq("user_id", data.user_id).limit(1).execute().data
    old = int(cur[0]["extra_slots"]) if cur else 0
    new = old + data.slots
    supabase.table("xera_name_change_allowance").upsert(
        {"user_id": data.user_id, "extra_slots": new}, on_conflict="user_id").execute()
    _log_admin_action(admin_id, "NAME_CHANGE_GRANT", {"user_id": data.user_id, "extra_slots": old},
                      {"user_id": data.user_id, "extra_slots": new}, data.reason)
    return {"status": "ok", "user_id": data.user_id, "extra_slots": new}
