"""
Legacy balance migration — one-time Merkle claim of pre-blockchain XERA
balances. Entirely separate from ongoing mining claims
(xera.chain.claims) — a different table
(xera_migration_snapshot), a different contract (XeraMigrationClaim), a
different identifier namespace (leaf_index, not reference_id), and a
different on-chain contract, so the two can never collide.

=== BNB-ONLY BY DESIGN (Phase 13 decision) ===

Legacy migration happens on **BNB Smart Chain only**. There is
deliberately no TON migration path, and this module rejects chain='TON'
rather than silently appearing to support it.

Rationale — a global "claim exactly once across both chains" guarantee is
genuinely hard for the legacy snapshot, and materially harder than it is
for mining claims:

  * Mining claims get their cross-chain single-use guarantee from the
    backend's atomic Supabase reservation (xera_reserve_onchain_claim),
    because every mining claim MUST pass through the backend to obtain a
    signature. The backend is an unavoidable chokepoint.
  * A Merkle migration claim has no such chokepoint. The proof is
    published to the user, and XeraMigrationClaim.claim() is
    permissionless by design — anyone holding a valid proof can call it
    directly, with no backend involvement at all. That's the whole point
    of a Merkle distribution.
  * So if the same snapshot root were anchored on BOTH chains, a user
    could submit their proof on BNB and on TON and legitimately receive
    their legacy balance TWICE, and neither contract could detect it.
    Supabase's `claimed` flag would not prevent this — it records
    settlement after the fact, it does not gate it.

Deploying the snapshot on one chain only makes the double-claim
structurally impossible rather than merely discouraged. If a TON
migration is ever genuinely required, it needs a DIFFERENT design (e.g. a
backend-signed claim like mining uses, not an open Merkle proof) — not
simply anchoring the same root on a second chain.

NOTE: the `chain` column on xera_migration_snapshot and the `chain`
parameters below are retained (rather than removed) so the schema can
record WHICH chain a claim settled on, and so a future
differently-designed TON path wouldn't require a migration. They are not
an indication that TON is currently supported.
"""

from main import supabase
from xera.chain.config import get_chain_config, ChainConfigError
from xera.chain.onchain_indexer import verify_bnb_legacy_claim_tx, IndexerError

_XERA_DECIMALS = 18

# See the module docstring: legacy migration is BNB-only by design.
_MIGRATION_SUPPORTED_CHAINS = ("BNB",)


class MigrationClaimError(Exception):
    pass


def _to_wei(amount_decimal) -> int:
    return int(round(float(amount_decimal) * (10 ** _XERA_DECIMALS)))


def get_snapshot_status(user_id: int) -> dict:
    res = supabase.table("xera_migration_snapshot").select("*").eq("user_id", user_id).limit(1).execute()
    if not res.data:
        return {"has_legacy_balance": False}

    row = res.data[0]
    return {
        "has_legacy_balance": True,
        "leaf_index": row["leaf_index"],
        "legacy_balance": row["legacy_balance"],
        "claimed": row["claimed"],
        "claimed_chain": row.get("claimed_chain"),
        "claimed_tx_hash": row.get("claimed_tx_hash"),
        "merkle_proof": row.get("merkle_proof") or [],
    }


def prepare_claim(user_id: int, chain: str) -> dict:
    chain = chain.upper()
    if chain not in _MIGRATION_SUPPORTED_CHAINS:
        # Fail loudly rather than pretending TON migration exists — see
        # this module's docstring for why it's BNB-only by design.
        raise MigrationClaimError("migration_chain_not_supported")
    res = supabase.table("xera_migration_snapshot").select("*").eq("user_id", user_id).limit(1).execute()
    if not res.data:
        raise MigrationClaimError("no_legacy_balance")
    row = res.data[0]
    if row["claimed"]:
        raise MigrationClaimError("already_claimed")
    if not row.get("merkle_proof"):
        raise MigrationClaimError("proof_not_generated")

    try:
        chain_cfg = get_chain_config(chain)
    except ChainConfigError as e:
        raise MigrationClaimError(str(e))

    migration_address = chain_cfg.get("xera_migration_address")
    if not migration_address:
        raise MigrationClaimError("migration_not_configured")

    return {
        "chain": chain,
        "contract_address": migration_address,
        "leaf_index": row["leaf_index"],
        "amount_wei": str(_to_wei(row["legacy_balance"])),
        "merkle_proof": row["merkle_proof"],
    }


def confirm_claim(user_id: int, transaction_hash: str, chain: str) -> dict:
    chain = chain.upper()
    if chain not in _MIGRATION_SUPPORTED_CHAINS:
        raise MigrationClaimError("migration_chain_not_supported")
    res = supabase.table("xera_migration_snapshot").select("*").eq("user_id", user_id).limit(1).execute()
    if not res.data:
        raise MigrationClaimError("no_legacy_balance")
    row = res.data[0]
    if row["claimed"]:
        return row

    try:
        chain_cfg = get_chain_config(chain)
    except ChainConfigError as e:
        raise MigrationClaimError(str(e))

    migration_address = chain_cfg.get("xera_migration_address")
    if not migration_address:
        raise MigrationClaimError("migration_not_configured")

    wallet_res = (
        supabase.table("xera_external_wallets")
        .select("address")
        .eq("user_id", user_id).eq("chain", chain).eq("status", "VERIFIED")
        .limit(1).execute()
    )
    if not wallet_res.data:
        raise MigrationClaimError("no_verified_wallet")
    account = wallet_res.data[0]["address"]

    if chain == "BNB":
        try:
            verify_bnb_legacy_claim_tx(
                tx_hash=transaction_hash,
                migration_address=migration_address,
                expected_leaf_index=row["leaf_index"],
                expected_account=account,
                expected_amount_wei=_to_wei(row["legacy_balance"]),
            )
        except IndexerError as e:
            raise MigrationClaimError(str(e))
    else:
        # Unreachable: the _MIGRATION_SUPPORTED_CHAINS guard at the top of
        # this function already rejects anything but BNB. Kept as a
        # defence-in-depth assertion so adding a chain to that tuple
        # without also implementing its verification path fails loudly
        # instead of silently confirming an unverified claim.
        raise MigrationClaimError("migration_chain_not_supported")

    result = supabase.rpc("xera_claim_legacy_migration", {
        "p_user_id": user_id,
        "p_chain": chain,
        "p_tx_hash": transaction_hash,
    }).execute()
    return result.data[0] if result.data else row
