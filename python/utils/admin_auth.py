"""
Admin session tokens for EvosHub.

A lightweight HMAC-signed token (not a full JWT library) — same spirit as
the agent tokens used elsewhere in the Evoxera stack. The token just proves
"this request was issued a valid session for user id X before it expired";
every actual authorization check (is this user still an active admin agent?)
is re-verified live against the database on each request in routes/admin.py,
so revoking an agent's access takes effect immediately even though the
token itself remains technically valid until it expires.
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

# --- brute-force lockout -----------------------------------------------
#
# slowapi's per-IP rate limit (10/minute on /admin/login) stops a single
# fast attacker, but not someone spraying slow, spread-out guesses at one
# account, or the same guess from many IPs. This adds a second, orthogonal
# layer: track failures per *identifier* (the username/email being
# attacked) as well as per *IP*, and lock either one out temporarily once
# it crosses a threshold — so both "many passwords against one account"
# and "one password against many accounts from one source" get caught.
#
# CAVEAT: this state is in-process memory, not shared across instances or
# survivable across a restart/deploy. That's an acceptable trade-off for a
# single-instance Render deployment; if this ever runs on multiple
# instances behind a load balancer, move this to a shared store (e.g. a
# Supabase table or Redis) so lockouts are consistent across instances.
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_WINDOW_SECONDS = 15 * 60
_LOCKOUT_DURATION_SECONDS = 15 * 60

_failure_log: dict[str, list[float]] = {}
_lock = threading.Lock()


def _prune(timestamps: list[float], now: float) -> list[float]:
    return [t for t in timestamps if now - t < _LOCKOUT_WINDOW_SECONDS]


def is_locked(key: str) -> tuple[bool, int]:
    """Returns (locked, seconds_remaining)."""
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
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64encode(payload_bytes)
    signature = hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    signature_b64 = _b64encode(signature)
    return f"{payload_b64}.{signature_b64}"


class AdminTokenInvalid(Exception):
    """Raised when an admin session token is missing, malformed, tampered, or expired."""


def verify_admin_token(token: str) -> int:
    """Returns the verified user id (bigint) if the token is valid and unexpired."""
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
