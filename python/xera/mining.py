"""
XERA mining rate + session service.

Base free-mining rewards are determined by the number of currently active,
unexpired mining sessions. Paid/boost hashrate is intentionally separate.
The database RPCs remain responsible for atomic session creation and claims.
"""

from datetime import date, datetime, timezone

from main import supabase
from xera.config import get_config, get_mining_config, get_allocations
from xera.launch import LaunchError, is_function_missing, launch_status

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
    Live base reward for the NEXT session, as calculated by the database
    (xera_launch_status). Python holds no reward table: the tier schedule and
    the active-miner count live in Postgres so display and payout cannot drift.
    """
    alloc = get_allocations()
    mining_cfg = get_mining_config()

    remaining_allocation = max(
        float(alloc["mining_allocation"]) - float(alloc["mining_distributed"]), 0.0
    )
    try:
        status = launch_status(None)
    except LaunchError:
        raise MiningError("launch_not_ready")

    scheduled = float(status.get("base_reward_estimate") or 0)
    rate = min(scheduled, remaining_allocation) if remaining_allocation > 0 else 0.0

    return {
        "rate": round(rate, 4),
        "remaining_allocation": round(remaining_allocation, 4),
        "remaining_days": _remaining_mining_days(mining_cfg),
        "active_miners": int(status.get("active_miners") or 0),
    }


_START_DB_CODES = (
    "agreement_required", "active_session_exists", "wallet_not_active",
    "free_mining_closed", "allocation_exhausted",
)


def start_session(user_id: int) -> dict:
    """
    Start a session through the single atomic database function. The database
    checks the agreement for the CURRENT version, picks the tier reward, creates
    the session and (only after it exists) awards the early-miner bonus.
    Python sends only the authenticated user id, the session length and the
    per-session cap - never a rate and never a bonus flag.
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
        for code in _START_DB_CODES:
            if code in msg:
                raise MiningError(code)
        raise

    out = res.data
    if isinstance(out, list):
        out = out[0] if out else None
    # A session is only "started" if the database says it has a session id.
    if not isinstance(out, dict) or not out.get("session_id"):
        raise RuntimeError("xera_start_mining_launch returned no session")

    return {
        "id": out["session_id"],
        "user_id": out.get("user_id", user_id),
        "status": out.get("status", "ACTIVE"),
        "started_at": out.get("started_at"),
        "expires_at": out.get("expires_at"),
        "rate_snapshot": out.get("rate_snapshot"),
        "estimated_reward": out.get("estimated_reward"),
        "active_miners": out.get("active_miners"),
        "new_balance": out.get("new_balance"),
        "bonus": {
            "status": out.get("bonus_status"),
            "amount": out.get("bonus_amount"),
            "slot": out.get("bonus_slot"),
        },
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
