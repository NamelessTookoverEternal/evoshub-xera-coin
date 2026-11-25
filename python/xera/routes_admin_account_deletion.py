"""
Admin side of account deletion. Mounted in main.py as:

    from xera.routes_admin_account_deletion import router as xera_admin_account_deletion_router
    app.include_router(xera_admin_account_deletion_router, prefix="/api/admin/xera/account-deletion", tags=["xera-admin-account-deletion"])

  GET  /      recent deletion requests (pending, cancelled, completed)
  POST /run   finish every request whose date has passed, now
  POST /cancel  cancel one person's scheduled deletion (support: they asked, or it was a mistake)

Settings (SQL):
    UPDATE xera_account_deletion_config SET grace_days = 14 WHERE id = 1;
    UPDATE xera_account_deletion_config SET enabled = false WHERE id = 1;
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from main import supabase, limiter
from xera import account_deletion
from xera.routes_admin import _require_admin, _log_admin_action

logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)


@router.get("")
@limiter.limit("60/minute")
def list_deletions(request: Request, authorization: str = Header(default=""), status: str | None = None,
                   limit: int = 50, offset: int = 0):
    _require_admin(request, authorization)
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    q = supabase.table("xera_account_deletions").select(
        "id,user_id,status,requested_at,purge_after,cancelled_at,completed_at,forfeited_balance")
    if status in ("PENDING", "CANCELLED", "COMPLETED"):
        q = q.eq("status", status)
    return {"status": "ok", "deletions": q.order("id", desc=True).range(offset, offset + limit - 1).execute().data or []}


@router.post("/run")
@limiter.limit("10/minute")
def run_now(request: Request, authorization: str = Header(default="")):
    admin_id = _require_admin(request, authorization)
    result = account_deletion.process_due()
    _log_admin_action(admin_id, "ACCOUNT_DELETION_RUN", {}, result)
    return {"status": "ok", **result}


class CancelRequest(BaseModel):
    user_id: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=300)


@router.post("/cancel")
@limiter.limit("20/minute")
def admin_cancel(request: Request, data: CancelRequest, authorization: str = Header(default="")):
    admin_id = _require_admin(request, authorization)
    try:
        supabase.rpc("xera_cancel_account_deletion", {"p_user_id": data.user_id}).execute()
    except Exception as e:
        if "no_pending_deletion" in str(e):
            raise HTTPException(status_code=404, detail="No deletion is scheduled for that user.")
        raise HTTPException(status_code=500, detail="Could not cancel.")
    _log_admin_action(admin_id, "ACCOUNT_DELETION_CANCEL", {"user_id": data.user_id}, {"status": "CANCELLED"}, data.reason)
    return {"status": "ok", "user_id": data.user_id}
