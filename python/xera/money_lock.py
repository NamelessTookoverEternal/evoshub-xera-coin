"""
Money lock: a locked account can still sign in, see its balance, mine, receive transfers and
contact support, but it cannot SEND (in-app P2P transfer) or WITHDRAW (on-chain claim).

The lock rows live in xera_money_locks (migration 20261119_xera_p2p_autolock_v4.sql). This module only
READS them (the scan and the unlock are Postgres functions called from routes_admin_p2p.py and p2p.py).
It deliberately does not use xera_wallets.status = 'SUSPENDED', because that state also blocks mining.
It does not touch the on-chain claim code: the routes call ensure_not_locked() before they call it.
"""
import logging

from fastapi import HTTPException

from main import supabase

logger = logging.getLogger(__name__)

LOCK_MESSAGE = "Transfers and withdrawals are paused: suspected breach of agreement. Contact support for details."


def _table_missing(err: Exception) -> bool:
    msg = str(err)
    return "xera_money_locks" in msg and any(k in msg for k in ("does not exist", "PGRST205", "schema cache", "42P01"))


def is_locked(user_id: int) -> bool:
    try:
        res = supabase.table("xera_money_locks").select("locked").eq("user_id", user_id).limit(1).execute()
    except Exception as e:
        if _table_missing(e):
            return False  # migration v4 not applied yet: nothing can be locked
        logger.error("Money lock check failed for user %s: %s", user_id, e)
        # Fail closed: a lookup problem must not let money move out of a possibly locked account.
        raise HTTPException(status_code=503, detail="Please try again in a moment.")
    return bool(res.data and res.data[0].get("locked"))


def ensure_not_locked(user_id: int) -> None:
    if is_locked(user_id):
        raise HTTPException(status_code=403, detail=LOCK_MESSAGE)


def auto_lock_enabled() -> bool:
    try:
        res = supabase.table("xera_p2p_config").select("auto_lock_enabled").eq("id", 1).limit(1).execute()
        return bool(res.data and res.data[0].get("auto_lock_enabled"))
    except Exception:
        return False  # column missing (v4 not applied) or a transient error: do not scan


def run_scan() -> list[dict]:
    """Lock every account covered by a current flag. No-op while the switch is off. Never raises."""
    try:
        rows = supabase.rpc("xera_p2p_autolock_scan", {}).execute().data or []
        if rows:
            logger.warning("XERA auto-lock locked %d account(s)", len(rows))
        return rows
    except Exception as e:
        logger.error("XERA auto-lock scan failed: %s", e)
        return []
