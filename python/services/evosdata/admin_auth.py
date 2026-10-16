"""
EVOSDATA admin authentication — DashXera and any other internal admin tool.

Deliberately reuses the exact scheme already running in evoshub and XERA
(ADMIN_TOKEN_SECRET env var, same HMAC token format, same admin_agents
gating table in the shared Supabase project) rather than inventing a
separate EVOSDATA admin login. Per evoshub's own docstring: "one shared
account per person across the Evoxera ecosystem, no separate admin account
to manage." Someone already active in admin_agents from working on
EvosHub or XERA can sign into DashXera with the same username and
password — no new account, no separate roster to maintain.

The code is duplicated (not imported across repos) because this module
ships inside the Evosdata service, a separate deployment from evoshub —
but the algorithm, secret name, and table are intentionally identical so
a single login covers all three.

SECURITY MODEL
- A correct public.users password is necessary but not sufficient. The
  account must also have an active row in admin_agents (user_id,
  is_active = true). Checked on login AND on every single admin request,
  so revoking access (flip is_active off) takes effect on that admin's
  very next request, not just after their token expires.
- Unknown-identifier and wrong-password responses are identical in both
  content and timing — a dummy bcrypt hash is always verified against,
  even when no matching user exists — so login can't be used to
  enumerate valid usernames or emails.
- "Not an active admin" and "wrong password" are distinguished in the
  response (the frontend can say "this account isn't an admin" instead
  of "wrong password"), but only after the password has already been
  verified — so this never confirms an account exists to someone who
  doesn't know its password.
- Per-identifier AND per-IP brute-force lockout, independent of the
  route's own rate limiter, so slow or distributed guessing is caught too.
- Tokens are opaque, HMAC-signed, short-lived (12h), and carry no
  authority by themselves — admin_agents.is_active is re-checked live
  against the database on every call, never trusted from the token.
"""

import base64
import hashlib
import hmac
import json
import os
import threading
import time
from typing import Optional, Tuple

_TOKEN_TTL_SECONDS = 12 * 60 * 60  # 12 hours

_LOCKOUT_THRESHOLD = 5
_LOCKOUT_WINDOW_SECONDS = 15 * 60
_LOCKOUT_DURATION_SECONDS = 15 * 60

_failure_log: dict = {}
_lock = threading.Lock()


def _prune(timestamps, now):
    return [t for t in timestamps if now - t < _LOCKOUT_WINDOW_SECONDS]


def is_locked(key: str) -> Tuple[bool, int]:
    now = time.time()
    with _lock:
        timestamps = _prune(_failure_log.get(key, []), now)
        _failure_log[key] = timestamps
        if len(timestamps) < _LOCKOUT_THRESHOLD:
            return False, 0
        locked_until = timestamps[-1] + _LOCKOUT_DURATION_SECONDS
        remaining = locked_until - now
        if remaining <= 0:
            _failure_log[key] = []
            return False, 0
        return True, int(remaining)


def record_failure(key: str) -> None:
    now = time.time()
    with _lock:
        timestamps = _prune(_failure_log.get(key, []), now)
        timestamps.append(now)
        _failure_log[key] = timestamps


def clear_failures(key: str) -> None:
    with _lock:
        _failure_log.pop(key, None)


def _secret() -> bytes:
    secret = os.getenv("ADMIN_TOKEN_SECRET", "")
    if not secret:
        raise RuntimeError(
            "ADMIN_TOKEN_SECRET is not set. This is the same secret used by "
            "evoshub and XERA admin login — set it to the same value here "
            "so a session token works across the ecosystem, or generate a "
            "fresh one if EVOSDATA's admin sessions should stay separate."
        )
    return secret.encode("utf-8")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def make_admin_token(user_id: int) -> str:
    payload = {"uid": user_id, "exp": int(time.time()) + _TOKEN_TTL_SECONDS}
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature_b64 = _b64encode(hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest())
    return f"{payload_b64}.{signature_b64}"


class AdminTokenInvalid(Exception):
    pass


def verify_admin_token(token: str) -> int:
    if not token or "." not in token:
        raise AdminTokenInvalid("Missing or malformed token.")

    payload_b64, _, signature_b64 = token.partition(".")
    expected_sig = hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    try:
        given_sig = _b64decode(signature_b64)
    except Exception:
        raise AdminTokenInvalid("Malformed token signature.")

    if not hmac.compare_digest(expected_sig, given_sig):
        raise AdminTokenInvalid("Invalid token signature.")

    try:
        payload = json.loads(_b64decode(payload_b64))
    except Exception:
        raise AdminTokenInvalid("Malformed token payload.")

    if payload.get("exp", 0) < time.time():
        raise AdminTokenInvalid("Token expired.")

    user_id = payload.get("uid")
    if not isinstance(user_id, int):
        raise AdminTokenInvalid("Token missing user id.")

    return user_id


def require_active_admin(supabase, token: str) -> Tuple[int, Optional[str]]:
    """
    Verifies the bearer token AND that the account still has an active
    admin_agents row. Raises AdminTokenInvalid (-> 401) or PermissionError
    (-> 403); callers map those to HTTP responses. This is the single
    choke point every DashXera route depends on.

    Returns (user_id, display_name) — display_name comes from admin_agents
    itself (that's what the column is for) and is used as the audit-trail
    actor, so "who did this reprocess" is the verified identity, never a
    client-supplied label.
    """
    user_id = verify_admin_token(token)  # raises AdminTokenInvalid if bad/expired

    agent = (
        supabase.table("admin_agents")
        .select("is_active, display_name")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not agent.data or not agent.data[0].get("is_active"):
        raise PermissionError("Admin access has been revoked.")

    return user_id, agent.data[0].get("display_name")
