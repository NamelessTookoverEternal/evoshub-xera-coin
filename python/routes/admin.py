"""
/api/admin — Admin login for EvosHub.

Reuses the same credentials as EvosData/EVOSGPT (public.users.username /
public.users.password, bcrypt-hashed) — there's one shared account per
person across the Evoxera ecosystem, no separate admin account to manage.

SECURITY MODEL
- Access is gated by admin_agents: a correct password alone is not enough
  to get in. The user must also have an active row in admin_agents
  (user_id, is_active = true) — the same table your evoxera_status
  trigger maintains. This is checked on both login AND on every /me call,
  so revoking access (flip evoxera_status off) takes effect on the next
  request, not just after the token expires.
- Wrong-password and unknown-identifier responses are indistinguishable
  in both content and timing (a dummy bcrypt hash is always verified
  against, even when no user was found), so this endpoint can't be used
  to enumerate valid usernames/emails.
- "Not an active admin" and "wrong password" are also never distinguished
  in a way that would confirm an account exists without an active admin
  role — both real users are just told they're not authorized, only after
  their password already checked out.
- Brute-force lockout (utils.admin_auth) tracks failures per identifier
  AND per IP, independent of the per-IP rate limiter below, so slow or
  distributed guessing is caught too.
- Session tokens are opaque, HMAC-signed, short-lived (12h), and carry no
  authority by themselves — every request re-verifies admin_agents.is_active
  live against the database rather than trusting a claim baked into the
  token.
"""

import re

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from utils.admin_auth import (
    AdminTokenInvalid,
    clear_failures,
    is_locked,
    make_admin_token,
    pwd_context,
    record_failure,
    verify_admin_token,
)
from utils.supabase_admin import (
    get_admin_agent,
    get_public_user_by_id,
    get_public_user_by_identifier,
    list_website_requests,
    update_website_request_status,
    list_chat_messages,
    insert_admin_chat_message,
)
from utils.rate_limit import get_client_ip, limiter

router = APIRouter()

_DUMMY_HASH = "$2b$12$KIXzCq3C3T6tFkUd9nj6aO.WwSIFqh4fQieFzpxKx5Mj5.z1rklHC"

# Usernames/emails only ever contain these characters in this system
# (see routes elsewhere: username has no spaces, email is EmailStr on
# registration). Rejecting anything else here is defense in depth against
# malformed input reaching the DB layer at all, on top of the parameterized
# lookups in get_public_user_by_identifier.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._%+\-@]{1,120}$")


class AdminLoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=120, description="Username or email")
    password: str = Field(..., min_length=1, max_length=200)

    @field_validator("identifier")
    @classmethod
    def _check_identifier(cls, v: str) -> str:
        v = v.strip()
        if not _IDENTIFIER_RE.match(v):
            raise ValueError("Invalid identifier format.")
        return v.lower()


def _agent_profile(user: dict, agent: dict | None) -> dict:
    return {
        "id": user["id"],
        "username": user.get("username"),
        "email": user.get("email"),
        "full_name": user.get("full_name"),
        "role": user.get("role"),
        "display_name": (agent or {}).get("display_name") or user.get("full_name"),
        "is_active_agent": bool(agent and agent.get("is_active")),
    }


@router.post("/admin/login")
@limiter.limit("10/minute")
async def admin_login(request: Request, data: AdminLoginRequest):
    identifier = data.identifier
    ip = get_client_ip(request)

    # Check both lockout dimensions before doing any DB/bcrypt work at all.
    id_locked, id_remaining = is_locked(f"id:{identifier}")
    ip_locked, ip_remaining = is_locked(f"ip:{ip}")
    if id_locked or ip_locked:
        retry_after = max(id_remaining, ip_remaining)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {retry_after} seconds.",
        )

    user = await get_public_user_by_identifier(identifier)
    stored_hash = user.get("password") if user else _DUMMY_HASH

    try:
        password_ok = pwd_context.verify(data.password, stored_hash)
    except Exception:
        password_ok = False

    if not user or not password_ok:
        record_failure(f"id:{identifier}")
        record_failure(f"ip:{ip}")
        return {"status": "invalid_credentials"}

    agent = await get_admin_agent(user["id"])
    if not agent or not agent.get("is_active"):
        # Correct password, but not an active admin agent. Still counted as
        # a failure against both counters — a correct password paired with
        # repeated attempts is exactly the "found valid creds, testing
        # authorization" pattern lockout exists to slow down.
        record_failure(f"id:{identifier}")
        record_failure(f"ip:{ip}")
        return {"status": "not_authorized"}

    clear_failures(f"id:{identifier}")
    clear_failures(f"ip:{ip}")

    token = make_admin_token(user["id"])
    return {"status": "ok", "token": token, "user": _agent_profile(user, agent)}


@router.get("/admin/me")
@limiter.limit("60/minute")
async def admin_me(request: Request, authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()

    try:
        user_id = verify_admin_token(token)
    except AdminTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")

    agent = await get_admin_agent(user_id)
    if not agent or not agent.get("is_active"):
        raise HTTPException(status_code=403, detail="Admin access has been revoked.")

    user = await get_public_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=403, detail="Account not found.")

    return {"status": "ok", "user": _agent_profile(user, agent)}


# --- Website-request inbox ---------------------------------------------------------
#
# These talk to Supabase via the service_role key (see utils/supabase_admin.py)
# instead of letting the browser call Supabase directly. Reason: RLS on
# website_requests / website_chat_messages is built around auth.uid(), and
# admin agents never get a Supabase Auth session (they authenticate against
# public.users + admin_agents above) — so there is no auth.uid() for them to
# satisfy. _require_active_admin() re-verifies the same bearer token and
# admin_agents.is_active check as /admin/me on every single call, which is
# what actually authorizes these requests in place of RLS.

async def _require_active_admin(authorization: str) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id = verify_admin_token(token)
    except AdminTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")

    agent = await get_admin_agent(user_id)
    if not agent or not agent.get("is_active"):
        raise HTTPException(status_code=403, detail="Admin access has been revoked.")

    return {"user_id": user_id, "agent": agent}


class StatusUpdateRequest(BaseModel):
    status: str = Field(..., min_length=1, max_length=40)


class SendMessageRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


@router.get("/admin/website-requests")
@limiter.limit("60/minute")
async def admin_list_website_requests(request: Request, authorization: str = Header(default="")):
    await _require_active_admin(authorization)
    requests_ = await list_website_requests()
    return {"status": "ok", "requests": requests_}


@router.get("/admin/website-requests/{request_id}/messages")
@limiter.limit("120/minute")
async def admin_list_messages(request: Request, request_id: str, authorization: str = Header(default="")):
    await _require_active_admin(authorization)
    messages = await list_chat_messages(request_id)
    return {"status": "ok", "messages": messages}


@router.post("/admin/website-requests/{request_id}/messages")
@limiter.limit("60/minute")
async def admin_send_message(
    request: Request,
    request_id: str,
    data: SendMessageRequest,
    authorization: str = Header(default=""),
):
    admin = await _require_active_admin(authorization)
    body = data.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message body cannot be empty.")
    message = await insert_admin_chat_message(request_id, body, admin["user_id"])
    return {"status": "ok", "message": message}


@router.patch("/admin/website-requests/{request_id}/status")
@limiter.limit("60/minute")
async def admin_update_status(
    request: Request,
    request_id: str,
    data: StatusUpdateRequest,
    authorization: str = Header(default=""),
):
    await _require_active_admin(authorization)
    updated = await update_website_request_status(request_id, data.status)
    return {"status": "ok", "request": updated}
