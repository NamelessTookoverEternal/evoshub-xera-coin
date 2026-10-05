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
    """
    The user's ledger rows. `id` is the row's own primary key (kept — other
    parts of the app rely on it). `reference_id` is the business key the
    on-chain claim layer looks entitlements up by (for MINING_REWARD rows it
    is the mining session id) — the frontend MUST send reference_id, not id,
    to /api/xera/claim/sign.

    MINING_REWARD rows additionally carry `onchain_claim_status`
    (None | SIGNED | SUBMITTED | CONFIRMED | FAILED | EXPIRED) and
    `onchain_claim_chain`, so the UI can show "settled" / "in progress"
    instead of offering a claim that would be rejected. Display-only: the
    backend re-checks everything when a claim is actually requested.
    """
    res = (
        supabase.table("xera_transactions")
        .select("id, reference_id, type, amount, direction, status, created_at, metadata")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data or []

    refs = [r["reference_id"] for r in rows if r.get("type") == "MINING_REWARD" and r.get("reference_id")]
    claims_by_ref: dict = {}
    if refs:
        try:
            claim_res = (
                supabase.table("xera_onchain_claims")
                .select("reference_id, status, chain, signature_deadline")
                .eq("user_id", user_id)
                .in_("reference_id", refs)
                .execute()
            )
            claims_by_ref = {c["reference_id"]: c for c in (claim_res.data or [])}
        except Exception:
            claims_by_ref = {}  # chain tables not migrated yet / transient error — status is cosmetic

    for r in rows:
        if r.get("type") == "MINING_REWARD":
            claim = claims_by_ref.get(r.get("reference_id"))
            r["onchain_claim_status"] = claim["status"] if claim else None
            r["onchain_claim_chain"] = claim["chain"] if claim else None
            r["onchain_claim_deadline"] = claim.get("signature_deadline") if claim else None
    return rows
