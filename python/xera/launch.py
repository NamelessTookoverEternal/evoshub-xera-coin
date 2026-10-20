"""
XERA official launch service: status, agreement acceptance, welcome notice.

Everything authoritative lives in Postgres (supabase/migrations/
20261021_xera_official_launch_v1.sql). This module only:
  * calls those RPCs with the user id taken from the verified token,
  * checks that this code's agreement version/hash is the one the database
    currently requires, and refuses to record acceptance if they disagree,
  * turns database error codes into short machine-readable codes.

Nothing here stores acceptance, eligibility or balances in the browser or in
process memory.
"""

import logging

from main import supabase
from xera.agreement import AGREEMENT_SHA256, AGREEMENT_VERSION

logger = logging.getLogger(__name__)


class LaunchError(Exception):
    """Raised with a short machine-readable code; routes.py maps it to HTTP."""


# Postgres error text -> code. Order matters only for readability.
_DB_CODES = (
    "agreement_version_mismatch",
    "invalid_content_hash",
    "user_not_found",
    "notice_version_mismatch",
)


def is_function_missing(exc: Exception) -> bool:
    """True when PostgREST says the RPC does not exist (migration not applied yet)."""
    msg = str(exc)
    return "PGRST202" in msg or "Could not find the function" in msg


def launch_status(user_id: int | None = None) -> dict:
    """Aggregate launch numbers; adds per-user flags only for the caller's own id."""
    params = {"p_user_id": user_id} if user_id is not None else {}
    try:
        res = supabase.rpc("xera_launch_status", params).execute()
    except Exception as e:
        if is_function_missing(e):
            raise LaunchError("launch_not_ready")
        raise
    data = res.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        raise LaunchError("launch_not_ready")
    return data


def _db_agreement_matches(status: dict) -> bool:
    return status.get("agreement_version") == AGREEMENT_VERSION


def public_launch_info() -> dict:
    """Public, aggregate-only view (no per-user fields)."""
    return public_launch_info_from(launch_status(None))


def user_launch_info(user_id: int) -> dict:
    """Aggregate view plus the caller's own flags. user_id must come from the token."""
    s = launch_status(user_id)
    out = public_launch_info_from(s)
    out["agreement_accepted"] = bool(s.get("agreement_accepted"))
    out["bonus_received"] = bool(s.get("bonus_received"))
    out["welcome_seen"] = bool(s.get("welcome_seen"))
    # If the code and the database disagree about the agreement version, the
    # client must not be shown an acceptance prompt it cannot complete.
    out["agreement_consistent"] = _db_agreement_matches(s)
    return out


def public_launch_info_from(s: dict) -> dict:
    return {
        "active_miners": s.get("active_miners"),
        "base_reward_estimate": s.get("base_reward_estimate"),
        "bonus_enabled": bool(s.get("bonus_enabled")),
        "bonus_amount": s.get("bonus_amount"),
        "bonus_total_slots": s.get("bonus_total_slots"),
        "bonus_slots_remaining": s.get("bonus_slots_remaining"),
        "agreement_version": s.get("agreement_version"),
        "welcome_notice_version": s.get("welcome_notice_version"),
    }


def accept_agreement(user_id: int, version: str, content_sha256: str,
                     ip: str | None, user_agent: str | None) -> dict:
    """
    Record acceptance for the authenticated user. Idempotent (a retry or a
    double click returns already_accepted). Rejects anything that is not the
    exact version AND text this server currently publishes.
    """
    if version != AGREEMENT_VERSION:
        raise LaunchError("agreement_version_mismatch")
    if content_sha256 != AGREEMENT_SHA256:
        raise LaunchError("agreement_hash_mismatch")

    # Fail safe if the database requires a different version than this code
    # ships (half-deployed state): recording a hash of the wrong text would be
    # worse than refusing.
    if not _db_agreement_matches(launch_status(None)):
        logger.error("XERA AGREEMENT VERSION DISAGREES WITH DATABASE CONFIG")
        raise LaunchError("agreement_unavailable")

    try:
        res = supabase.rpc("xera_accept_miner_agreement", {
            "p_user_id": user_id,
            "p_version": AGREEMENT_VERSION,
            "p_content_hash": AGREEMENT_SHA256,
            "p_ip": ip,
            "p_user_agent": user_agent,
        }).execute()
    except Exception as e:
        if is_function_missing(e):
            raise LaunchError("launch_not_ready")
        msg = str(e)
        for code in _DB_CODES:
            if code in msg:
                raise LaunchError(code)
        raise

    data = res.data
    if isinstance(data, list):
        data = data[0] if data else {}
    return {
        "accepted": bool((data or {}).get("accepted")),
        "already_accepted": bool((data or {}).get("already_accepted")),
        "agreement_version": (data or {}).get("agreement_version"),
        "accepted_at": (data or {}).get("accepted_at"),
    }


def mark_welcome_seen(user_id: int, notice_version: str) -> dict:
    try:
        supabase.rpc("xera_mark_launch_notice_seen", {
            "p_user_id": user_id,
            "p_version": notice_version,
        }).execute()
    except Exception as e:
        if is_function_missing(e):
            raise LaunchError("launch_not_ready")
        msg = str(e)
        if "notice_version_mismatch" in msg:
            raise LaunchError("notice_version_mismatch")
        raise
    return {"welcome_seen": True}
