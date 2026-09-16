"""
Section 5/6/16: turns a finalized Supabase mining entitlement into a
signed, chain-specific claim, and later confirms its on-chain settlement.

This module NEVER calculates a reward amount — it only reads the amount
already committed in xera_transactions (written by
xera_claim_mining_reward, see mining.py) and authorizes moving exactly
that amount on-chain, once.
"""

import os
import time

from eth_utils import keccak

from main import supabase
from xera.chain.config import get_chain_config, require_onchain_enabled, ChainConfigError
from xera.chain import eip712_signer
from xera.chain import ton_claim_signer
from xera.chain.onchain_indexer import verify_bnb_claim_tx, verify_ton_claim_tx, IndexerError

_CLAIM_SIGNATURE_TTL_SECONDS = 15 * 60
_XERA_DECIMALS = 18


class ClaimError(Exception):
    """Short machine-readable code; routes_chain.py maps these to HTTP responses."""


def _reference_id_to_bytes32(reference_id: str) -> bytes:
    return keccak(text=reference_id)


def _to_wei(amount_decimal) -> int:
    return int(round(float(amount_decimal) * (10 ** _XERA_DECIMALS)))


def _get_confirmed_mining_tx(user_id: int, reference_id: str) -> dict:
    res = (
        supabase.table("xera_transactions")
        .select("*")
        .eq("user_id", user_id)
        .eq("reference_id", reference_id)
        .eq("type", "MINING_REWARD")
        .eq("status", "CONFIRMED")
        .limit(1)
        .execute()
    )
    if not res.data:
        raise ClaimError("entitlement_not_found")
    return res.data[0]


def _get_verified_wallet(user_id: int, chain: str) -> dict:
    res = (
        supabase.table("xera_external_wallets")
        .select("*")
        .eq("user_id", user_id)
        .eq("chain", chain.upper())
        .eq("status", "VERIFIED")
        .limit(1)
        .execute()
    )
    if not res.data:
        raise ClaimError("no_verified_wallet")
    return res.data[0]


def sign_claim(user_id: int, reference_id: str, chain: str) -> dict:
    chain = chain.upper()

    # 2/3/4: reference_id belongs to this user, is a real finalized
    # entitlement, and hasn't already been claimed on-chain (any chain —
    # the reservation insert below is the atomic single-source-of-truth
    # check; the pre-check here just gives a faster/clearer error).
    tx = _get_confirmed_mining_tx(user_id, reference_id)
    amount_decimal = tx["amount"]

    existing = supabase.table("xera_onchain_claims").select("id,chain,status").eq("reference_id", reference_id).limit(1).execute()
    if existing.data:
        raise ClaimError("already_claimed_or_reserved")

    # 6: valid linked wallet for the requested chain.
    wallet = _get_verified_wallet(user_id, chain)

    try:
        chain_cfg = require_onchain_enabled(chain)
    except ChainConfigError as e:
        raise ClaimError(str(e))

    amount_wei = _to_wei(amount_decimal)
    transferable_wei = (amount_wei * 2500) // 10000
    locked_wei = amount_wei - transferable_wei

    deadline_unix = int(time.time()) + _CLAIM_SIGNATURE_TTL_SECONDS
    reference_id_bytes32 = _reference_id_to_bytes32(reference_id)

    # 7: atomic reservation — this is what makes reference_id single-use
    # across BNB + TON combined (section 17). A concurrent/duplicate
    # attempt (this chain or the other one) fails on the DB unique index,
    # never on a race in application code.
    try:
        supabase.rpc("xera_reserve_onchain_claim", {
            "p_reference_id": reference_id,
            "p_user_id": user_id,
            "p_chain": chain,
            "p_wallet_address": wallet["address"],
            "p_claimed_amount": float(amount_decimal),
            "p_transferable_amount": transferable_wei / (10 ** _XERA_DECIMALS),
            "p_locked_amount": locked_wei / (10 ** _XERA_DECIMALS),
            "p_contract_address": chain_cfg["xera_distributor_address"],
            "p_deadline": _iso_from_unix(deadline_unix),
        }).execute()
    except Exception as e:
        if "reference_already_reserved" in str(e):
            raise ClaimError("already_claimed_or_reserved")
        if "global_mining_allocation_exceeded" in str(e):
            # The 75,000,000 GLOBAL mining cap (across BNB + TON combined)
            # is enforced atomically in Postgres — see
            # xera_reserve_onchain_claim in
            # supabase/migrations/20260914_xera_blockchain_hardening.sql.
            # Surfacing it as a distinct error matters: this is not the
            # user's fault and is not retryable by them, unlike
            # already_claimed_or_reserved.
            raise ClaimError("global_mining_allocation_exceeded")
        raise

    if chain == "BNB":
        chain_id = int(os.getenv("BNB_CHAIN_ID", "97"))  # 97 = testnet, 56 = mainnet
        signature = eip712_signer.sign_bnb_claim(
            user_address=wallet["address"],
            amount_wei=amount_wei,
            reference_id_bytes32=reference_id_bytes32,
            deadline_unix=deadline_unix,
            chain_id=chain_id,
            verifying_contract=chain_cfg["xera_distributor_address"],
        )
        return {
            "chain": "BNB",
            "contract_address": chain_cfg["xera_distributor_address"],
            "chain_id": chain_id,
            "user": wallet["address"],
            "amount_wei": str(amount_wei),
            "reference_id_hash": "0x" + reference_id_bytes32.hex(),
            "deadline": deadline_unix,
            "signature": signature,
            "transferable_wei": str(transferable_wei),
            "locked_wei": str(locked_wei),
        }

    # TON: signature format verified end-to-end against the actual
    # compiled contract in a TON sandbox — see
    # blockchain/ton/tests/XeraMiningDistributor.claimSignature.spec.ts
    # and python/tests/test_ton_claim_signer.py (pinned fixed vector).
    # queryId is a fresh random 63-bit value (must fit TON's uint64 minus
    # sign-safety margin) — it has no security role (the hash already
    # binds every security-relevant field), it just needs to be non-zero
    # for the wallet's own message deduplication conventions.
    query_id = int.from_bytes(os.urandom(7), "big")
    ton_result = ton_claim_signer.sign_claim_configured(
        query_id=query_id,
        user_address=wallet["address"],
        amount_nano=amount_wei,  # TON "nano" units use the same 1e-18... see note below
        reference_id=reference_id,
        deadline_unix=deadline_unix,
    )
    # NOTE on decimals: TON's native "nano" unit is 1e-9 (nanotons), but
    # Jettons (including XERA on TON) define their OWN decimals field in
    # the minter's content, and this codebase's XeraJettonMinter uses 18
    # decimals (see jetton_minter.tact) to stay numerically identical to
    # the BNB side — so `amount_wei` (1e18-scaled) is the correct Jetton
    # `amount` here, matching XeraMiningDistributor.tact's `storeCoins`
    # call on the SAME scaled integer XeraToken.sol uses. This is a
    # deliberate consistency choice, not a units bug — flagged here since
    # "nano" naming makes 1e-9 an easy wrong assumption.
    return {
        "chain": "TON",
        "contract_address": chain_cfg["xera_distributor_address"],
        "query_id": str(query_id),
        "user": wallet["address"],
        "amount_wei": str(amount_wei),
        "reference_id": reference_id,
        "reference_id_uint256": str(ton_result["reference_id_uint256"]),
        "deadline": deadline_unix,
        "signature": "0x" + ton_result["signature_hex"],
        "transferable_wei": str(transferable_wei),
        "locked_wei": str(locked_wei),
    }


def _iso_from_unix(unix_ts: int) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(unix_ts, tz=datetime.timezone.utc).isoformat()


def confirm_claim(user_id: int, reference_id: str, transaction_hash: str) -> dict:
    res = supabase.table("xera_onchain_claims").select("*").eq("reference_id", reference_id).limit(1).execute()
    if not res.data:
        raise ClaimError("claim_not_found")
    row = res.data[0]
    if row["user_id"] != user_id:
        raise ClaimError("not_your_claim")
    if row["status"] == "CONFIRMED":
        return row

    if row["chain"] == "BNB":
        expected_reference_id_bytes32 = _reference_id_to_bytes32(reference_id)
        expected_total_wei = _to_wei(row["claimed_amount"])
        try:
            result = verify_bnb_claim_tx(
                tx_hash=transaction_hash,
                distributor_address=row["contract_address"],
                expected_user=row["wallet_address"],
                expected_reference_id_bytes32=expected_reference_id_bytes32,
                expected_total_amount_wei=expected_total_wei,
            )
        except IndexerError as e:
            supabase.rpc("xera_mark_onchain_claim_failed", {"p_reference_id": reference_id}).execute()
            raise ClaimError(str(e))

        confirmed = supabase.rpc("xera_confirm_onchain_claim", {
            "p_reference_id": reference_id,
            "p_transaction_hash": transaction_hash,
            "p_block_number": result["block_number"],
        }).execute()
        return confirmed.data[0] if confirmed.data else row

    if row["chain"] == "TON":
        expected_total_wei = _to_wei(row["claimed_amount"])
        try:
            result = verify_ton_claim_tx(
                tx_hash=transaction_hash,
                distributor_address=row["contract_address"],
                expected_user_address=row["wallet_address"],
                expected_reference_id=reference_id,
                expected_total_amount_nano=expected_total_wei,
            )
        except IndexerError as e:
            supabase.rpc("xera_mark_onchain_claim_failed", {"p_reference_id": reference_id}).execute()
            raise ClaimError(str(e))

        confirmed = supabase.rpc("xera_confirm_onchain_claim", {
            "p_reference_id": reference_id,
            "p_transaction_hash": transaction_hash,
            "p_block_number": result["block_number"],
        }).execute()
        return confirmed.data[0] if confirmed.data else row

    raise ClaimError("unsupported_chain")


def retry_claim(user_id: int, reference_id: str, chain: str) -> dict:
    """
    Phase 6 recovery path: re-activates a FAILED/EXPIRED claim (same row,
    same reference_id — see xera_retry_onchain_claim's docstring for why
    this can never become a second claim opportunity) with a fresh
    signature, optionally on a different chain than the original attempt.
    """
    chain = chain.upper()
    res = supabase.table("xera_onchain_claims").select("*").eq("reference_id", reference_id).limit(1).execute()
    if not res.data:
        raise ClaimError("claim_not_found")
    row = res.data[0]
    if row["user_id"] != user_id:
        raise ClaimError("not_your_claim")
    if row["status"] not in ("FAILED", "EXPIRED"):
        raise ClaimError("claim_not_retryable")

    wallet = _get_verified_wallet(user_id, chain)
    try:
        chain_cfg = require_onchain_enabled(chain)
    except ChainConfigError as e:
        raise ClaimError(str(e))

    deadline_unix = int(time.time()) + _CLAIM_SIGNATURE_TTL_SECONDS

    try:
        supabase.rpc("xera_retry_onchain_claim", {
            "p_reference_id": reference_id,
            "p_chain": chain,
            "p_wallet_address": wallet["address"],
            "p_contract_address": chain_cfg["xera_distributor_address"],
            "p_deadline": _iso_from_unix(deadline_unix),
        }).execute()
    except Exception as e:
        if "global_mining_allocation_exceeded" in str(e):
            raise ClaimError("global_mining_allocation_exceeded")
        if "claim_not_retryable" in str(e):
            raise ClaimError("claim_not_retryable")
        raise

    amount_wei = _to_wei(row["claimed_amount"])
    transferable_wei = (amount_wei * 2500) // 10000
    locked_wei = amount_wei - transferable_wei
    reference_id_bytes32 = _reference_id_to_bytes32(reference_id)

    if chain == "BNB":
        chain_id = int(os.getenv("BNB_CHAIN_ID", "97"))
        signature = eip712_signer.sign_bnb_claim(
            user_address=wallet["address"], amount_wei=amount_wei,
            reference_id_bytes32=reference_id_bytes32, deadline_unix=deadline_unix,
            chain_id=chain_id, verifying_contract=chain_cfg["xera_distributor_address"],
        )
        return {
            "chain": "BNB", "contract_address": chain_cfg["xera_distributor_address"],
            "chain_id": chain_id, "user": wallet["address"], "amount_wei": str(amount_wei),
            "reference_id_hash": "0x" + reference_id_bytes32.hex(), "deadline": deadline_unix,
            "signature": signature, "transferable_wei": str(transferable_wei), "locked_wei": str(locked_wei),
        }

    query_id = int.from_bytes(os.urandom(7), "big")
    ton_result = ton_claim_signer.sign_claim_configured(
        query_id=query_id, user_address=wallet["address"], amount_nano=amount_wei,
        reference_id=reference_id, deadline_unix=deadline_unix,
    )
    return {
        "chain": "TON", "contract_address": chain_cfg["xera_distributor_address"],
        "query_id": str(query_id), "user": wallet["address"], "amount_wei": str(amount_wei),
        "reference_id": reference_id, "reference_id_uint256": str(ton_result["reference_id_uint256"]),
        "deadline": deadline_unix, "signature": "0x" + ton_result["signature_hex"],
        "transferable_wei": str(transferable_wei), "locked_wei": str(locked_wei),
    }
