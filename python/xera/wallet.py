"""
XERA wallet reads.

Nothing in this module writes a balance directly (no
`.update({"cached_balance": ...})` anywhere) — every balance change goes
through the xera_claim_mining_reward / xera_admin_adjust_balance Postgres
functions in the migration, which are the only things allowed to touch
xera_wallets.cached_balance. This module is read-only on purpose.
"""

from main import supabase


def get_or_create_wallet(user_id: int) -> dict:
    res = supabase.table("xera_wallets").select("*").eq("user_id", user_id).limit(1).execute()
    if res.data:
        return res.data[0]
    # Insert-if-missing race is fine here: user_id is UNIQUE on xera_wallets,
    # so a concurrent duplicate insert fails and we just re-read.
    try:
        created = supabase.table("xera_wallets").insert({"user_id": user_id}).execute()
        return created.data[0]
    except Exception:
        res = supabase.table("xera_wallets").select("*").eq("user_id", user_id).limit(1).execute()
        if res.data:
            return res.data[0]
        raise


def get_transactions(user_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
    res = (
        supabase.table("xera_transactions")
        .select("id, type, amount, direction, status, created_at, metadata")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return res.data or []
