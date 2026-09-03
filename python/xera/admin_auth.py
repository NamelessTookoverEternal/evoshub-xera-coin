"""
XERA admin authentication.

Deliberately reuses evoshub's exact scheme (ADMIN_TOKEN_SECRET env var,
same HMAC token format, same admin_agents gating table in the shared
Supabase project) rather than inventing a separate XERA admin login. Per
evoshub's own docstring: "one shared account per person across the
Evoxera ecosystem, no separate admin account to manage." An admin who is
already active in admin_agents can use the same token here.

The code is duplicated (not imported across repos) because this module
ships inside the Evosdata service, a separate deployment from evoshub —
but the algorithm, secret name, and table are intentionally identical so
a single login covers both.

SECURITY MODEL (unchanged from evoshub):
- Correct password is necessary but not sufficient — the user must also
  have an active row in admin_agents. Checked on login AND on every
  request, so revoking access takes effect immediately.
- Unknown-identifier and wrong-password responses are identical in both
  content and timing (a dummy bcrypt hash is always verified against).
- Per-identifier AND per-IP brute-force lockout, independent of the
  route's rate limiter.
- Tokens are opaque, HMAC-signed, short-lived (12h), and carry no
  authority by themselves — admin_agents.is_active is re-checked live
  against the DB on every call.
"""

import base64
import hashlib
import hmac
import json
import os
import threading
import time

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_TOKEN_TTL_SECONDS = 12 * 60 * 60  # 12 hours
_DUMMY_HASH = "$2b$12$KIXzCq3C3T6tFkUd9nj6aO.WwSIFqh4fQieFzpxKx5Mj5.z1rklHC"

_LOCKOUT_THRESHOLD = 5
_LOCKOUT_WINDOW_SECONDS = 15 * 60
_LOCKOUT_DURATION_SECONDS = 15 * 60

_failure_log: dict[str, list[float]] = {}
_lock = threading.Lock()


def _prune(timestamps: list[float], now: float) -> list[float]:
    return [t for t in timestamps if now - t < _LOCKOUT_WINDOW_SECONDS]


def is_locked(key: str) -> tuple[bool, int]:
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
        raise RuntimeError("ADMIN_TOKEN_SECRET not configured.")
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


def require_active_admin(supabase, authorization: str) -> int:
    """
    Verifies the bearer token AND that the user still has an active
    admin_agents row. Raises AdminTokenInvalid (→ 401) or PermissionError
    (→ 403) — routes.py maps these to HTTP responses. This is the single
    choke point every /phasepage/xera/* admin route calls first.
    """
    token = authorization.removeprefix("Bearer ").strip()
    user_id = verify_admin_token(token)  # raises AdminTokenInvalid if bad/expired

    agent = supabase.table("admin_agents").select("is_active").eq("user_id", user_id).limit(1).execute()
    if not agent.data or not agent.data[0].get("is_active"):
        raise PermissionError("Admin access has been revoked.")

    return user_id
