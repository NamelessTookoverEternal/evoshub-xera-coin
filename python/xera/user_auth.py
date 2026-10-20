"""
XERA user session tokens.

Every existing user-facing table in this app (agent_wallets, orders, etc.)
is currently reached by trusting a bare `user_id` the frontend sends in the
request body. That's fine for the existing endpoints given today's threat
model, but it is explicitly not acceptable for a token-accounting system
(section 16 of the brief): anyone could pass a different user_id and read
or, worse, act on someone else's wallet.

This module issues a small HMAC-signed, expiring token — same scheme as
evoshub's admin_auth.py (base64url JSON payload + HMAC-SHA256 signature,
dot-separated), but with its own secret (XERA_TOKEN_SECRET) so a leak of
ADMIN_SECRET or evoshub's ADMIN_TOKEN_SECRET can't be used to forge XERA
wallet access, and vice versa.

The token is issued by /auth/login (see INTEGRATION.md) once the password
has already been verified there — this module never verifies a password
itself, only proves "this request was already authenticated as user X
before this token's expiry."
"""

import base64
import hashlib
import hmac
import json
import os
import time

# Why this is not 24h any more: the Hub session token is shared by XERA, EVOS
# Data and EVOSGPT, and EVOS Data's own tokens last 30 days. A 24h Hub token
# meant someone signed in yesterday was asked for their password again the next
# day when opening XERA (it had nothing to do with the mining session length).
# Default 7 days, overridable with XERA_TOKEN_TTL_SECONDS, clamped to 1h..30d.
_MIN_TTL = 60 * 60
_MAX_TTL = 30 * 24 * 60 * 60
_DEFAULT_TTL = 7 * 24 * 60 * 60


def token_ttl_seconds() -> int:
    raw = os.getenv("XERA_TOKEN_TTL_SECONDS", "")
    try:
        ttl = int(raw) if raw else _DEFAULT_TTL
    except ValueError:
        ttl = _DEFAULT_TTL
    return min(max(ttl, _MIN_TTL), _MAX_TTL)


# A refreshed token keeps the original sign-in time. Refreshing can extend a
# session only up to this absolute limit, then a real login is required, so a
# leaked token cannot be kept alive forever.
MAX_SESSION_SECONDS = _MAX_TTL


def _secret() -> bytes:
    secret = os.getenv("XERA_TOKEN_SECRET", "")
    if not secret:
        raise RuntimeError("XERA_TOKEN_SECRET not configured.")
    return secret.encode("utf-8")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def make_user_token(user_id: int, session_start: int | None = None) -> str:
    now = int(time.time())
    payload = {
        "uid": user_id,
        "exp": now + token_ttl_seconds(),
        "ses": int(session_start) if session_start else now,  # original sign-in time
    }
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature_b64 = _b64encode(hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest())
    return f"{payload_b64}.{signature_b64}"


class XeraTokenInvalid(Exception):
    """Missing, malformed, tampered, or expired XERA session token."""


def verify_user_token(token: str) -> int:
    """Returns the verified user id if the token checks out."""
    return int(verify_user_token_payload(token)["uid"])


def verify_user_token_payload(token: str) -> dict:
    """Full verified payload (uid, exp, ses). Raises XeraTokenInvalid otherwise."""
    if not token or "." not in token:
        raise XeraTokenInvalid("Missing or malformed token.")

    payload_b64, _, signature_b64 = token.partition(".")

    expected_sig = hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    try:
        given_sig = _b64decode(signature_b64)
    except Exception:
        raise XeraTokenInvalid("Malformed token signature.")

    if not hmac.compare_digest(expected_sig, given_sig):
        raise XeraTokenInvalid("Invalid token signature.")

    try:
        payload = json.loads(_b64decode(payload_b64))
    except Exception:
        raise XeraTokenInvalid("Malformed token payload.")

    if payload.get("exp", 0) < time.time():
        raise XeraTokenInvalid("Token expired.")

    user_id = payload.get("uid")
    if not isinstance(user_id, int):
        raise XeraTokenInvalid("Token missing user id.")

    return payload
