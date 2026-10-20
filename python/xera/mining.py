"""
XERA mining rate + session service.

Base free-mining rewards are determined by the number of currently active,
unexpired mining sessions. Paid/boost hashrate is intentionally separate.
The database RPCs remain responsible for atomic session creation and claims.
"""

from datetime import date, datetime, timezone

from main import supabase
from xera.config import get_config, get_mining_config, get_allocations
from xera.wallet import get_or_create_wallet

DEFAULT_MINING_PERIOD_DAYS = 90


class MiningError(Exception):
    """Raised with a short machine-readable code; routes.py maps these to HTTP responses."""


def _remaining_mining_days(mining_cfg: dict) -> int:
    end = mining_cfg.get("mining_end")
    if not end:
        return DEFAULT_MINING_PERIOD_DAYS
    end_date = date.fromisoformat(end) if isinstance(end, str) else end
    return max((end_date - date.today()).days, 1)


def _active_miners_count() -> int:
    """Count only sessions that are marked ACTIVE and have not expired."""
    now = datetime.now(timezone.utc).isoformat()
    res = (
        supabase.table("xera_mining_sessions")
        .select("id", count="exact")
        .eq("status", "ACTIVE")
        .gt("expires_at", now)
        .execute()
    )
    return max(res.count or 0, 0)


def _base_reward_for_active_miners(active_miners: int) -> float:
    """Base free-mining reward per completed 24-hour session."""
    if active_miners <= 100:
        return 10.0
    if active_miners <= 200:
        return 8.0
    if active_miners <= 500:
        return 5.0
    if active_miners <= 1000:
        return 3.0
    if active_miners <= 1500:
        return 2.5
    if active_miners <= 2000:
        return 2.0
    if active_miners <= 3000:
        return 1.5
    return 1.0


def current_rate() -> dict:
    """Return the live base reward and the active-miner count used to choose it."""
    alloc = get_allocations()
    mining_cfg = get_mining_config()

    remaining_allocation = max(
        float(alloc["mining_allocation"]) - float(alloc["mining_distributed"]), 0.0
    )
    remaining_days = _remaining_mining_days(mining_cfg)
    active_miners = _active_miners_count()
    scheduled_reward = _base_reward_for_active_miners(active_miners)

    # Do not advertise a positive rate if the mining allocation is exhausted.
    rate = min(scheduled_reward, remaining_allocation) if remaining_allocation > 0 else 0.0

    return {
        "rate": round(rate, 4),
        "remaining_allocation": round(remaining_allocation, 4),
        "remaining_days": remaining_days,
        "active_miners": active_miners,
    }


def start_session(user_id: int) -> dict:
    cfg = get_config()
    if not cfg["system_enabled"] or not cfg["mining_enabled"]:
        raise MiningError("mining_disabled")

    mining_cfg = get_mining_config()
    rate_info = current_rate()
    if rate_info["rate"] <= 0:
        raise MiningError("allocation_exhausted")

    get_or_create_wallet(user_id)

    try:
        res = supabase.rpc("xera_start_mining_session", {
            "p_user_id": user_id,
            "p_rate": rate_info["rate"],
            "p_hours": mining_cfg["session_hours"],
            "p_max_reward": float(mining_cfg["max_reward_per_session"]),
        }).execute()
    except Exception as e:
        msg = str(e)
        for code in (
            "active_session_exists", "wallet_not_active", "free_mining_closed",
        ):
            if code in msg:
                raise MiningError(code)
        raise

    return res.data


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
