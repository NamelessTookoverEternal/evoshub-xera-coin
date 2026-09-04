"""
XERA daily claim service.

A once-per-calendar-day bonus, deliberately separate from the 24-hour
mining session in mining.py — it resets at UTC midnight rather than
running its own 24h timer, so a user can mine and claim daily
independently of one another. The DB write (check-not-already-claimed,
credit ledger, bump streak) happens inside xera_claim_daily_reward, a
single Postgres transaction, for the same race-safety reasons documented
in mining.py.
"""

from datetime import date, timedelta

from main import supabase
from xera.wallet import get_or_create_wallet


class DailyClaimError(Exception):
    """Raised with a short machine-readable code; routes.py maps these to HTTP responses."""


def get_daily_config() -> dict:
    res = supabase.table("xera_daily_config").select("*").eq("id", 1).limit(1).execute()
    if not res.data:
        raise RuntimeError("xera_daily_config row missing — run the daily-claim migration.")
    return res.data[0]


def _parse_date(value):
    if value is None:
        return None
    return date.fromisoformat(value) if isinstance(value, str) else value


def get_daily_status(user_id: int) -> dict:
    cfg = get_daily_config()
    res = supabase.table("xera_daily_claims").select("*").eq("user_id", user_id).limit(1).execute()
    row = res.data[0] if res.data else None

    today = date.today()
    last = _parse_date(row.get("last_claim_date")) if row else None
    already_claimed_today = last == today

    return {
        "enabled": bool(cfg["enabled"]),
        "reward_amount": float(cfg["reward_amount"]),
        "can_claim": bool(cfg["enabled"]) and not already_claimed_today,
        "already_claimed_today": already_claimed_today,
        "streak": (row or {}).get("streak", 0),
        "total_claims": (row or {}).get("total_claims", 0),
        "next_reset_at": (today + timedelta(days=1)).isoformat() + "T00:00:00Z",
    }


def claim_daily(user_id: int) -> dict:
    cfg = get_daily_config()
    if not cfg["enabled"]:
        raise DailyClaimError("daily_claim_disabled")

    get_or_create_wallet(user_id)  # ensures the wallet row exists before the RPC locks it

    try:
        res = supabase.rpc("xera_claim_daily_reward", {
            "p_user_id": user_id,
            "p_reward": float(cfg["reward_amount"]),
        }).execute()
    except Exception as e:
        msg = str(e)
        for code in ("already_claimed_today", "wallet_not_active"):
            if code in msg:
                raise DailyClaimError(code)
        raise

    row = res.data[0] if res.data else {}
    return {
        "new_balance": row.get("new_balance"),
        "reward_credited": row.get("reward_credited"),
        "streak": row.get("streak"),
    }
