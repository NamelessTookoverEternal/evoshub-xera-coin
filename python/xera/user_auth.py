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

_TOKEN_TTL_SECONDS = 24 * 60 * 60  # 24h — matches a mining session's own lifetime


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


def make_user_token(user_id: int) -> str:
    payload = {"uid": user_id, "exp": int(time.time()) + _TOKEN_TTL_SECONDS}
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature_b64 = _b64encode(hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest())
    return f"{payload_b64}.{signature_b64}"


class XeraTokenInvalid(Exception):
    """Missing, malformed, tampered, or expired XERA session token."""


def verify_user_token(token: str) -> int:
    """Returns the verified user id if the token checks out."""
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

    return user_id
