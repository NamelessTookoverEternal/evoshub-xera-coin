"""
XERA admin API — NOT discoverable.

Mounted in main.py at an unpublished path (see INTEGRATION.md), and every
route below sets include_in_schema=False individually — not relying only
on the mount prefix, because the existing app currently leaves /docs,
/redoc and /openapi.json publicly enabled in production (worth fixing
separately; flagged in the summary at the end). Even with that gap, these
routes will not appear in the schema either way, and the real boundary is
require_active_admin() below, not the path name.

    from xera.routes_admin import router as xera_admin_router
    app.include_router(xera_admin_router, prefix="/api/admin/xera", tags=["xera-admin"])

Nothing here is linked from any public page, sitemap, or robots.txt, and
none of it should ever be referenced from user-facing frontend code —
only from a separate, non-public admin app/build, exactly like the
existing internal-admin convention used elsewhere in the ecosystem.
"""

import re
import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from main import supabase, limiter
from xera.admin_auth import (
    AdminTokenInvalid,
    clear_failures,
    is_locked,
    make_admin_token,
    pwd_context,
    record_failure,
    require_active_admin,
    _DUMMY_HASH,
)
from xera.config import get_config, get_mining_config, get_allocations

logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._%+\-@]{1,120}$")


def _get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _require_admin(request: Request, authorization: str) -> int:
    try:
        return require_active_admin(supabase, authorization)
    except AdminTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access has been revoked.")


def _log_admin_action(admin_id: int, action: str, old_value: dict, new_value: dict, reason: str | None = None):
    supabase.table("xera_admin_actions").insert({
        "admin_id": admin_id, "action": action,
        "old_value": old_value, "new_value": new_value, "reason": reason,
    }).execute()


# ------------------------------------------------------------
# LOGIN — identical logic to evoshub's /admin/login, same
# admin_agents gate and lockout, so one set of credentials
# works across both services.
# ------------------------------------------------------------

class AdminLoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=200)

    @field_validator("identifier")
    @classmethod
    def _check_identifier(cls, v: str) -> str:
        v = v.strip()
        if not _IDENTIFIER_RE.match(v):
            raise ValueError("Invalid identifier format.")
        return v.lower()


@router.post("/login", include_in_schema=False)
@limiter.limit("10/minute")
def admin_login(request: Request, data: AdminLoginRequest):
    identifier = data.identifier
    ip = _get_client_ip(request)

    id_locked, id_remaining = is_locked(f"id:{identifier}")
    ip_locked, ip_remaining = is_locked(f"ip:{ip}")
    if id_locked or ip_locked:
        raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {max(id_remaining, ip_remaining)} seconds.")

    user_res = supabase.table("users").select("*").or_(f"username.eq.{identifier},email.eq.{identifier}").limit(1).execute()
    user = user_res.data[0] if user_res.data else None
    stored_hash = user.get("password") if user else _DUMMY_HASH

    try:
        password_ok = pwd_context.verify(data.password, stored_hash)
    except Exception:
        password_ok = False

    if not user or not password_ok:
        record_failure(f"id:{identifier}")
        record_failure(f"ip:{ip}")
        return {"status": "invalid_credentials"}

    agent_res = supabase.table("admin_agents").select("is_active").eq("user_id", user["id"]).limit(1).execute()
    agent = agent_res.data[0] if agent_res.data else None
    if not agent or not agent.get("is_active"):
        record_failure(f"id:{identifier}")
        record_failure(f"ip:{ip}")
        return {"status": "not_authorized"}

    clear_failures(f"id:{identifier}")
    clear_failures(f"ip:{ip}")

    token = make_admin_token(user["id"])
    return {"status": "ok", "token": token, "user": {"id": user["id"], "username": user.get("username")}}


# ------------------------------------------------------------
# STATS / CONFIG
# ------------------------------------------------------------

@router.get("/stats", include_in_schema=False)
@limiter.limit("60/minute")
def admin_stats(request: Request, authorization: str = Header(default="")):
    _require_admin(request, authorization)
    cfg = get_config()
    alloc = get_allocations()
    active = supabase.table("xera_mining_sessions").select("id", count="exact").eq("status", "ACTIVE").execute()
    total_wallets = supabase.table("xera_wallets").select("id", count="exact").execute()
    return {
        "status": "ok",
        "current_phase": cfg["current_phase"],
        "total_users": total_wallets.count or 0,
        "active_miners": active.count or 0,
        "mining_allocation": alloc["mining_allocation"],
        "mining_distributed": alloc["mining_distributed"],
        "mining_remaining": float(alloc["mining_allocation"]) - float(alloc["mining_distributed"]),
        "flags": {k: cfg[k] for k in ("mining_enabled", "sale_enabled", "withdrawal_enabled", "transfer_enabled", "referral_enabled", "onchain_enabled")},
    }


@router.get("/config", include_in_schema=False)
@limiter.limit("60/minute")
def admin_get_config(request: Request, authorization: str = Header(default="")):
    _require_admin(request, authorization)
    return {
        "status": "ok",
        "config": get_config(),
        "mining_config": get_mining_config(),
        "allocations": get_allocations(),
    }


_ALLOWED_CONFIG_FLAGS = {
    "system_enabled", "mining_enabled", "sale_enabled",
    "withdrawal_enabled", "transfer_enabled", "referral_enabled",
    "onchain_enabled", "current_phase",
}


class ConfigUpdateRequest(BaseModel):
    updates: dict = Field(..., description="Subset of xera_config fields to change")
    reason: str | None = None


@router.put("/config", include_in_schema=False)
@limiter.limit("20/minute")
def admin_update_config(request: Request, data: ConfigUpdateRequest, authorization: str = Header(default="")):
    admin_id = _require_admin(request, authorization)

    disallowed = set(data.updates.keys()) - _ALLOWED_CONFIG_FLAGS
    if disallowed:
        raise HTTPException(status_code=400, detail=f"Cannot update fields: {sorted(disallowed)}")

    old = get_config()
    payload = {**data.updates, "updated_by": admin_id}
    supabase.table("xera_config").update(payload).eq("id", 1).execute()
    new = get_config()

    action_names = []
    if "mining_enabled" in data.updates:
        action_names.append("MINING_ENABLED" if data.updates["mining_enabled"] else "MINING_DISABLED")
    if "sale_enabled" in data.updates:
        action_names.append("SALE_ENABLED" if data.updates["sale_enabled"] else "SALE_DISABLED")
    if "withdrawal_enabled" in data.updates:
        action_names.append("WITHDRAWAL_ENABLED" if data.updates["withdrawal_enabled"] else "WITHDRAWAL_DISABLED")

    _log_admin_action(admin_id, ",".join(action_names) or "CONFIG_UPDATED", old, new, data.reason)
    return {"status": "ok", "config": new}


class AllocationUpdateRequest(BaseModel):
    updates: dict
    reason: str | None = None


@router.put("/allocations", include_in_schema=False)
@limiter.limit("10/minute")
def admin_update_allocations(request: Request, data: AllocationUpdateRequest, authorization: str = Header(default="")):
    admin_id = _require_admin(request, authorization)
    allowed = {"total_target", "mining_allocation", "sale_allocation", "community_allocation", "liquidity_allocation", "treasury_allocation"}
    disallowed = set(data.updates.keys()) - allowed
    if disallowed:
        raise HTTPException(status_code=400, detail=f"Cannot update fields: {sorted(disallowed)}")

    old = get_allocations()
    try:
        # The CHECK constraints on xera_allocations (sum <= total_target,
        # mining_distributed <= mining_allocation) do the real enforcement —
        # this call simply surfaces a clean error if they're violated.
        supabase.table("xera_allocations").update({**data.updates, "updated_by": admin_id}).eq("id", 1).execute()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Allocation update violates an accounting constraint (sum exceeds target, or below already-distributed amount).")
    new = get_allocations()
    _log_admin_action(admin_id, "ADMIN_ADJUSTED_ALLOCATION", old, new, data.reason)
    return {"status": "ok", "allocations": new}


class MiningConfigUpdateRequest(BaseModel):
    updates: dict
    reason: str | None = None


@router.put("/mining-config", include_in_schema=False)
@limiter.limit("10/minute")
def admin_update_mining_config(request: Request, data: MiningConfigUpdateRequest, authorization: str = Header(default="")):
    admin_id = _require_admin(request, authorization)
    allowed = {"session_hours", "mining_start", "mining_end", "min_reward_per_session", "max_reward_per_session"}
    disallowed = set(data.updates.keys()) - allowed
    if disallowed:
        raise HTTPException(status_code=400, detail=f"Cannot update fields: {sorted(disallowed)}")

    old = get_mining_config()
    supabase.table("xera_mining_config").update({**data.updates, "updated_by": admin_id}).eq("id", 1).execute()
    new = get_mining_config()
    _log_admin_action(admin_id, "MINING_RATE_CHANGED", old, new, data.reason)
    return {"status": "ok", "mining_config": new}


# ------------------------------------------------------------
# USER MANAGEMENT
# ------------------------------------------------------------

class AdjustBalanceRequest(BaseModel):
    amount: float = Field(..., gt=0)
    direction: str = Field(..., pattern="^(CREDIT|DEBIT)$")
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/users/{user_id}/adjust", include_in_schema=False)
@limiter.limit("10/minute")
def admin_adjust_balance(request: Request, user_id: int, data: AdjustBalanceRequest, authorization: str = Header(default="")):
    admin_id = _require_admin(request, authorization)
    try:
        res = supabase.rpc("xera_admin_adjust_balance", {
            "p_admin_id": admin_id, "p_user_id": user_id,
            "p_amount": data.amount, "p_direction": data.direction, "p_reason": data.reason,
        }).execute()
    except Exception as e:
        if "insufficient_balance" in str(e):
            raise HTTPException(status_code=400, detail="Insufficient balance for this debit.")
        raise HTTPException(status_code=400, detail="Could not adjust balance.")
    return {"status": "ok", "new_balance": res.data}


class SuspendRequest(BaseModel):
    suspended: bool
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/users/{user_id}/suspend", include_in_schema=False)
@limiter.limit("10/minute")
def admin_suspend_wallet(request: Request, user_id: int, data: SuspendRequest, authorization: str = Header(default="")):
    admin_id = _require_admin(request, authorization)
    new_status = "SUSPENDED" if data.suspended else "ACTIVE"
    old = supabase.table("xera_wallets").select("status").eq("user_id", user_id).limit(1).execute()
    supabase.table("xera_wallets").update({"status": new_status}).eq("user_id", user_id).execute()
    _log_admin_action(admin_id, "USER_SUSPENDED" if data.suspended else "USER_UNSUSPENDED",
                       {"status": old.data[0]["status"] if old.data else None},
                       {"status": new_status}, data.reason)
    return {"status": "ok", "wallet_status": new_status}


# ------------------------------------------------------------
# AUDIT / SECURITY
# ------------------------------------------------------------

@router.get("/security-events", include_in_schema=False)
@limiter.limit("30/minute")
def admin_security_events(request: Request, authorization: str = Header(default=""), limit: int = 50):
    _require_admin(request, authorization)
    res = supabase.table("xera_security_events").select("*").order("created_at", desc=True).limit(min(limit, 200)).execute()
    return {"status": "ok", "events": res.data or []}


@router.get("/actions", include_in_schema=False)
@limiter.limit("30/minute")
def admin_actions_log(request: Request, authorization: str = Header(default=""), limit: int = 50):
    _require_admin(request, authorization)
    res = supabase.table("xera_admin_actions").select("*").order("created_at", desc=True).limit(min(limit, 200)).execute()
    return {"status": "ok", "actions": res.data or []}


@router.get("/reconciliation", include_in_schema=False)
@limiter.limit("10/minute")
def admin_reconciliation(request: Request, authorization: str = Header(default="")):
    _require_admin(request, authorization)
    res = supabase.table("xera_reconciliation_report").select("*").execute()
    return {"status": "ok", "discrepancies": res.data or []}
