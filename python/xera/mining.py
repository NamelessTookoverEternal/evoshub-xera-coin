"""
XERA mining rate + session service.

The reward rate is computed here, in Python, at request time — never
hard-coded — from four live numbers (section 5/11 of the brief):

    daily_budget      = remaining_mining_allocation / remaining_mining_days
    per_user_reward   = daily_budget / active_miners

This is self-balancing: the pool is fixed, so as more people mine, each
person's cut shrinks automatically, and the system can never distribute
more than mining_allocation in total (the claim-side RPC enforces that
hard cap independently, in case this estimate and the real remaining
allocation drift apart between session start and claim).

The actual DB writes (insert session / credit reward) happen inside the
two Postgres RPC functions in migrations/20260901_xera_token_v1.sql, called via
supabase.rpc(...) — one network round trip, one Postgres transaction, so
there's no window for a duplicate start or a duplicate claim to slip in
between a check and a write.
"""

from datetime import date, timedelta

from main import supabase
from xera.config import get_config, get_mining_config, get_allocations
from xera.wallet import get_or_create_wallet

DEFAULT_MINING_PERIOD_DAYS = 90  # fallback if mining_end isn't set yet


class MiningError(Exception):
    """Raised with a short machine-readable code; routes.py maps these to HTTP responses."""


def _remaining_mining_days(mining_cfg: dict) -> int:
    end = mining_cfg.get("mining_end")
    if not end:
        return DEFAULT_MINING_PERIOD_DAYS
    end_date = date.fromisoformat(end) if isinstance(end, str) else end
    remaining = (end_date - date.today()).days
    return max(remaining, 1)


def _active_miners_count() -> int:
    res = supabase.table("xera_mining_sessions").select("id", count="exact").eq("status", "ACTIVE").execute()
    return max(res.count or 0, 1)  # floor at 1 so a lone first miner doesn't divide by zero


def current_rate() -> dict:
    """Returns the live per-session reward plus the inputs used to derive it, for transparency in the public stats endpoint."""
    alloc = get_allocations()
    mining_cfg = get_mining_config()

    remaining_allocation = float(alloc["mining_allocation"]) - float(alloc["mining_distributed"])
    remaining_days = _remaining_mining_days(mining_cfg)
    active_miners = _active_miners_count()

    daily_budget = max(remaining_allocation, 0) / remaining_days
    per_user_reward = daily_budget / active_miners

    clamped = min(max(per_user_reward, float(mining_cfg["min_reward_per_session"])), float(mining_cfg["max_reward_per_session"]))

    return {
        "rate": round(clamped, 4),
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

    get_or_create_wallet(user_id)  # ensures the wallet row exists before the RPC locks it

    try:
        res = supabase.rpc("xera_start_mining_session", {
            "p_user_id": user_id,
            "p_rate": rate_info["rate"],
            "p_hours": mining_cfg["session_hours"],
            "p_max_reward": float(mining_cfg["max_reward_per_session"]),
        }).execute()
    except Exception as e:
        msg = str(e)
        if "active_session_exists" in msg:
            raise MiningError("active_session_exists")
        if "wallet_not_active" in msg:
            raise MiningError("wallet_not_active")
        raise

    return res.data


def get_status(user_id: int) -> dict | None:
    res = (
        supabase.table("xera_mining_sessions")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "ACTIVE")
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
    return {"new_balance": row.get("new_balance"), "reward_credited": row.get("reward_credited")}
