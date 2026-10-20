"""
XERA mining session service.

The base reward schedule (10 -> 1 XERA by number of active, unexpired
sessions), the agreement check, the one-active-session rule and the
first-100 bonus all live in ONE Postgres function, xera_start_mining_launch,
so they are atomic and cannot be bypassed or raced from here. This module
holds no reward table of its own: it asks the database. Paid/boost hashrate
is intentionally separate (hashrate.py).
"""

from datetime import date, datetime, timezone

from main import supabase
from xera.config import get_config, get_mining_config, get_allocations
from xera.launch import LaunchError, launch_status, is_function_missing

DEFAULT_MINING_PERIOD_DAYS = 90


class MiningError(Exception):
    """Raised with a short machine-readable code; routes.py maps these to HTTP responses."""


def _remaining_mining_days(mining_cfg: dict) -> int:
    end = mining_cfg.get("mining_end")
    if not end:
        return DEFAULT_MINING_PERIOD_DAYS
    end_date = date.fromisoformat(end) if isinstance(end, str) else end
    return max((end_date - date.today()).days, 1)


def current_rate() -> dict:
    """
    Live base reward and the active-miner count it was chosen from, both read
    from the database's own calculation (xera_launch_status). Raises
    MiningError("launch_not_ready") if the launch migration is not applied.
    """
    try:
        info = launch_status(None)
    except LaunchError:
        raise MiningError("launch_not_ready")

    alloc = get_allocations()
    mining_cfg = get_mining_config()
    remaining_allocation = max(
        float(alloc["mining_allocation"]) - float(alloc["mining_distributed"]), 0.0
    )
    rate = float(info.get("base_reward_estimate") or 0) if remaining_allocation > 0 else 0.0

    return {
        "rate": round(rate, 4),
        "remaining_allocation": round(remaining_allocation, 4),
        "remaining_days": _remaining_mining_days(mining_cfg),
        "active_miners": int(info.get("active_miners") or 0),
    }


_START_ERRORS = (
    "agreement_required", "active_session_exists", "wallet_not_active",
    "free_mining_closed", "allocation_exhausted", "invalid_parameters",
)


def start_session(user_id: int) -> dict:
    """
    Start a mining session for the authenticated user.

    One database transaction: agreement check -> tiered reward -> session ->
    (optional) early-miner bonus. If anything fails nothing is committed, so a
    failed start never costs a bonus slot and never leaves a half-made session.
    Returns the session plus a "bonus" summary; only a real session is returned.
    """
    cfg = get_config()
    if not cfg["system_enabled"] or not cfg["mining_enabled"]:
        raise MiningError("mining_disabled")

    mining_cfg = get_mining_config()

    try:
        res = supabase.rpc("xera_start_mining_launch", {
            "p_user_id": user_id,
            "p_hours": int(mining_cfg["session_hours"]),
            "p_max_reward": float(mining_cfg["max_reward_per_session"]),
        }).execute()
    except Exception as e:
        if is_function_missing(e):
            raise MiningError("launch_not_ready")
        msg = str(e)
        for code in _START_ERRORS:
            if code in msg:
                raise MiningError(code)
        raise

    out = res.data
    if isinstance(out, list):
        out = out[0] if out else None
    if not isinstance(out, dict) or not out.get("session_id"):
        # Never report an active miner unless the database confirmed a session.
        raise RuntimeError("xera_start_mining_launch returned no session")

    return {
        "id": out["session_id"],
        "user_id": out.get("user_id"),
        "started_at": out.get("started_at"),
        "expires_at": out.get("expires_at"),
        "status": out.get("status"),
        "rate_snapshot": out.get("rate_snapshot"),
        "estimated_reward": out.get("estimated_reward"),
        "active_miners": out.get("active_miners"),
        "bonus": {
            "status": out.get("bonus_status"),
            "amount": out.get("bonus_amount") or 0,
            "slot": out.get("bonus_slot"),
        },
        "new_balance": out.get("new_balance"),
    }


def get_status(user_id: int) -> dict | None:
    res = (
        supabase.table("xera_mining_sessions")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "ACTIVE")
        .gt("expires_at", datetime.now(timezone.utc).isoformat())
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def claim(user_id: int, session_id: int) -> dict:
    cfg = get_config()
    if not cfg["system_enabled"] or not cfg["mining_enabled"]:
        raise MiningError("mining_disabled")

    try:
        res = supabase.rpc("xera_claim_mining_reward", {
            "p_session_id": session_id,
            "p_user_id": user_id,
        }).execute()
    except Exception as e:
        msg = str(e)
        for code in (
            "session_not_found", "invalid_session_status", "not_yet_expired",
            "allocation_exhausted", "wallet_not_active", "wallet_not_found",
        ):
            if code in msg:
                raise MiningError(code)
        raise

    row = res.data[0] if res.data else {}
    return {
        "new_balance": row.get("new_balance"),
        "reward_credited": row.get("reward_credited"),
    }
