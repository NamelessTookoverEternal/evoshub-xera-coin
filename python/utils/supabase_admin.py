"""
Server-side Supabase access.

Two very different keys are used here on purpose:

- SUPABASE_ANON_KEY  -> only ever used to *verify* a visitor's JWT against
  Supabase's own Auth server (GoTrue). It cannot be used to bypass RLS.
- SUPABASE_SERVICE_ROLE_KEY -> bypasses Row Level Security entirely. It must
  NEVER be sent to the browser, logged, or embedded in any response. It is
  read once from the environment and used only for the two operations this
  module exposes.

Both come from environment variables (.env locally, host env vars in
production) — never hard-code them.
"""

import os
import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class VisitorTokenInvalid(Exception):
    """Raised when a caller's Supabase access token doesn't check out."""


async def verify_visitor_token(access_token: str) -> str:
    """
    Verifies a Supabase auth access token by asking Supabase's own Auth
    server whose token it is. Returns the verified user id (auth.uid()).

    We deliberately do NOT trust any user id the client sends in the request
    body — only the id Supabase's Auth server confirms for this token. This
    is what prevents one visitor from writing a row/message as another.
    """
    if not access_token:
        raise VisitorTokenInvalid("Missing access token.")

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY not configured.")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {access_token}",
            },
        )

    if resp.status_code != 200:
        raise VisitorTokenInvalid("Could not verify visitor session.")

    user = resp.json()
    user_id = user.get("id")
    if not user_id:
        raise VisitorTokenInvalid("Verified session had no user id.")
    return user_id


async def get_public_user_by_identifier(identifier: str) -> dict | None:
    """
    Looks up the matching row in public.users by username OR email, using
    the service_role key. Deliberately issues two separate, safely
    parameterized requests instead of building a single manual
    `or=(username.eq.X,email.eq.X)` filter string — interpolating raw user
    input into a PostgREST filter expression is a filter-injection risk
    (a user-controlled comma/paren/operator could alter which rows match),
    even though it can't reach raw SQL. Passing the value only ever through
    httpx's `params` dict keeps it properly encoded as a single opaque
    value in every case.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured.")

    select = "id,username,email,full_name,role,password,evoxera_status"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"select": select, "username": f"eq.{identifier}", "limit": 1},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Supabase users lookup failed: {resp.status_code} {resp.text}")
        data = resp.json()
        if data:
            return data[0]

        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"select": select, "email": f"eq.{identifier}", "limit": 1},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Supabase users lookup failed: {resp.status_code} {resp.text}")
        data = resp.json()
        return data[0] if data else None


async def get_public_user_by_id(user_id: int) -> dict | None:
    """
    Looks up the matching row in public.users by (bigint) id, using the
    service_role key. Used to resolve an admin session token's user id
    back to a full profile.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured.")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            },
            params={
                "select": "id,username,email,full_name,role,evoxera_status",
                "id": f"eq.{user_id}",
                "limit": 1,
            },
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Supabase users lookup failed: {resp.status_code} {resp.text}")

    data = resp.json()
    return data[0] if data else None


async def get_admin_agent(user_id: int) -> dict | None:
    """
    Looks up the matching row in public.admin_agents by (bigint) user_id,
    using the service_role key.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured.")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/admin_agents",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            },
            params={
                "select": "user_id,display_name,is_active",
                "user_id": f"eq.{user_id}",
                "limit": 1,
            },
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Supabase admin_agents lookup failed: {resp.status_code} {resp.text}")

    data = resp.json()
    return data[0] if data else None


async def insert_website_request(row: dict) -> dict:
    """
    Inserts a row into public.website_requests using the service_role key,
    which is required here because the visitor's own anon-key session is
    still subject to RLS (that's fine for chat, but this endpoint also does
    server-side validation/sanitization/rate-limiting the DB constraints
    alone don't cover, so the insert happens from the trusted backend).
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured.")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/website_requests",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json=row,
        )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Supabase insert failed: {resp.status_code} {resp.text}")

    data = resp.json()
    return data[0] if isinstance(data, list) else data


# --- Admin website-request inbox --------------------------------------------------
#
# All service_role, on purpose: website_requests / website_chat_messages RLS
# is written around auth.uid(), which only exists for a real Supabase Auth
# session. Admin agents authenticate through public.users + admin_agents
# (bigint ids) and never get a Supabase Auth session, so there is no
# auth.uid() for them at all. The route handlers in routes/admin.py verify
# the admin bearer token and admin_agents.is_active BEFORE calling any of
# these — that check is what stands in for RLS here.

async def list_website_requests() -> list[dict]:
    """All website_requests rows, newest first."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured.")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/website_requests",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            },
            params={
                "select": "id,full_name,email,package,status,project_brief,created_at",
                "order": "created_at.desc",
            },
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Supabase website_requests list failed: {resp.status_code} {resp.text}")

    return resp.json()


async def update_website_request_status(request_id: str, status: str) -> dict:
    """Updates status on a single website_requests row by (uuid) id."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured.")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{SUPABASE_URL}/rest/v1/website_requests",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            params={"id": f"eq.{request_id}"},
            json={"status": status},
        )

    if resp.status_code not in (200, 204):
        raise RuntimeError(f"Supabase website_requests update failed: {resp.status_code} {resp.text}")

    data = resp.json() if resp.text else []
    return data[0] if isinstance(data, list) and data else {}


async def list_chat_messages(request_id: str) -> list[dict]:
    """All messages for one request thread, oldest first."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured.")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/website_chat_messages",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            },
            params={
                "select": "id,sender_role,body,created_at,admin_user_id",
                "request_id": f"eq.{request_id}",
                "order": "created_at.asc",
            },
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Supabase website_chat_messages list failed: {resp.status_code} {resp.text}")

    return resp.json()


# website_chat_messages.sender_id has a real foreign key to auth.users(id)
# (Supabase's built-in auth table) — but admin agents authenticate against
# public.users + admin_agents (bigint ids) and never get a Supabase Auth
# session, so there is no auth.uid() / auth.users row for them at all. No
# placeholder uuid can satisfy that FK, since it isn't a real auth.users row
# (confirmed via the 23503 foreign key violation in production logs).
#
# Fix: sender_id is now nullable and left NULL for admin-authored messages.
# admin_user_id (bigint, references public.users.id) records which real
# agent sent it instead — sender_role='admin' still marks authorship for
# rendering; admin_user_id is what lets you attribute it to a specific
# person if/when that's needed.

async def insert_admin_chat_message(request_id: str, body: str, admin_user_id: int) -> dict:
    """Inserts an admin-sent chat message, attributed to the real agent via
    admin_user_id rather than a fake sender_id placeholder."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured.")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/website_chat_messages",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json={
                "request_id": request_id,
                "sender_id": None,
                "sender_role": "admin",
                "admin_user_id": admin_user_id,
                "body": body,
            },
        )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Supabase website_chat_messages insert failed: {resp.status_code} {resp.text}")

    data = resp.json()
    return data[0] if isinstance(data, list) else data
