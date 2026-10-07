"""
Section 5/6/16: turns a finalized Supabase mining entitlement into a
signed, chain-specific claim, and later confirms its on-chain settlement.

This module NEVER calculates a reward amount — it only reads the amount
already committed in xera_transactions (written by
xera_claim_mining_reward, see mining.py) and authorizes moving exactly
that amount on-chain, once.
"""

import os
import re
import time
import uuid
from decimal import Decimal, InvalidOperation

from eth_utils import keccak

from main import supabase
from xera.chain.rpc import first_row
from xera.chain.config import get_chain_config, require_onchain_enabled, bnb_chain_id, ChainConfigError
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
        # A manually-entered address (status PENDING) is stored and displayed
        # but is NOT proof of ownership, so it can never satisfy a claim.
        # Report that precisely instead of a generic "no wallet".
        try:
            manual = (
                supabase.table("xera_external_wallets").select("id")
                .eq("user_id", user_id).eq("chain", chain.upper()).eq("status", "PENDING")
                .limit(1).execute()
            )
        except Exception:
            manual = None
        raise ClaimError("wallet_not_verified" if manual is not None and manual.data else "no_verified_wallet")
    return res.data[0]


def _sweep_expired_claims() -> None:
    """
    Runs the (already-existing) deadline sweep: SIGNED claims whose signature
    deadline has passed become EXPIRED and release their slice of the global
    allocation. The migration documents this as a periodic job, but nothing
    schedules it — without this a user who rejects the wallet popup would be
    stuck behind their own un-submitted signature forever. An expired
    signature can no longer be executed on-chain, so flipping the row is safe.
    Non-fatal: if it fails the caller just sees the claim as still in progress.
    """
    try:
        supabase.rpc("xera_expire_stale_onchain_claims", {}).execute()
    except Exception:
        pass


def sign_claim(user_id: int, reference_id: str, chain: str) -> dict:
    """
    LEGACY per-entitlement claim. Retained only so existing rows keep working
    and the original tests keep covering them. It is NOT exposed by the API any
    more: it reserves without debiting the in-app balance, so using it next to
    amount-based claims could move the same XERA twice. See sign_amount_claim.
    """
    chain = chain.upper()

    # 2/3/4: reference_id belongs to this user, is a real finalized
    # entitlement, and hasn't already been claimed on-chain (any chain —
    # the reservation insert below is the atomic single-source-of-truth
    # check; the pre-check here just gives a faster/clearer error).
    tx = _get_confirmed_mining_tx(user_id, reference_id)
    amount_decimal = tx["amount"]

    existing = supabase.table("xera_onchain_claims").select("id,user_id,chain,status").eq("reference_id", reference_id).limit(1).execute()
    if existing.data:
        row = existing.data[0]
        status = row["status"]
        if status == "CONFIRMED":
            raise ClaimError("claim_already_settled")
        if row["user_id"] != user_id:
            raise ClaimError("already_claimed_or_reserved")

        if status in ("SIGNED", "SUBMITTED"):
            _sweep_expired_claims()
            refreshed = supabase.table("xera_onchain_claims").select("status").eq("reference_id", reference_id).limit(1).execute()
            status = refreshed.data[0]["status"] if refreshed.data else status

        if status in ("SIGNED", "SUBMITTED"):
            raise ClaimError("claim_in_progress")
        if status in ("FAILED", "EXPIRED"):
            # Same single reservation row, re-signed — never a second claim.
            # Only auto-resumed on the SAME chain; switching chain stays an
            # explicit /claim/retry decision.
            if row["chain"] != chain:
                raise ClaimError("claim_on_other_chain")
            return retry_claim(user_id, reference_id, chain)
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
        chain_id = bnb_chain_id()  # XERA_BNB_CHAIN_ID: 97 = testnet, 56 = mainnet
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


# ------------------------------------------------------------------
# AMOUNT-BASED CLAIMS — the user chooses how much to move on-chain
# ------------------------------------------------------------------
# The reservation (balance check, balance debit, ledger row, global-cap check)
# is ONE atomic Postgres function: xera_reserve_onchain_claim_amount, see
# supabase/migrations/20261006_xera_amount_claims.sql. This module only
# validates the input, asks for the reservation, and signs it.

_TRANSFERABLE_FRACTION = Decimal("0.25")     # 25% to the wallet now, 75% locked in vesting
_AMOUNT_STEP = Decimal("0.01")               # at most 2 decimals — keeps the 25/75 split exact in NUMERIC(20,4)
_MAX_CLAIM_AMOUNT = Decimal("75000000")      # the whole pool; anything above is nonsense input


def min_claim_amount() -> Decimal:
    """Smallest claim allowed (stops dust claims that cost the user more in gas than they receive)."""
    try:
        value = Decimal(os.getenv("XERA_MIN_ONCHAIN_CLAIM", "1"))
    except InvalidOperation:
        value = Decimal("1")
    return max(value, _AMOUNT_STEP)


_PLAIN_AMOUNT = re.compile(r"[0-9]{1,9}(\.[0-9]{1,2})?")  # ASCII digits only ("\d" also matches e.g. Arabic-Indic digits)
_TOO_PRECISE = re.compile(r"[0-9]{1,9}\.[0-9]{3,}")


def parse_claim_amount(raw) -> Decimal:
    """
    Validate a user-supplied amount. Raises ClaimError with a precise code.
    Only plain decimal text is accepted ("12", "12.5", "12.50") — no signs,
    exponents ("1e3"), separators, spaces, NaN/Infinity — and at most 2 decimals.
    """
    if isinstance(raw, bool) or raw is None:
        raise ClaimError("invalid_amount")
    text = str(raw).strip()
    if _TOO_PRECISE.fullmatch(text):
        raise ClaimError("amount_too_precise")
    if not _PLAIN_AMOUNT.fullmatch(text):
        raise ClaimError("invalid_amount")
    amount = Decimal(text)
    if amount <= 0 or amount > _MAX_CLAIM_AMOUNT:
        raise ClaimError("invalid_amount")
    if amount < min_claim_amount():
        raise ClaimError("amount_below_minimum")
    return amount


def split_claim_amount(amount: Decimal) -> tuple:
    """(transferable, locked) as Decimals that add up to `amount` exactly."""
    transferable = amount * _TRANSFERABLE_FRACTION
    return transferable, amount - transferable


def _decimal_to_wei(amount: Decimal) -> int:
    return int(amount * (10 ** _XERA_DECIMALS))


def _build_signed_claim(chain, wallet, chain_cfg, reference_id, amount_wei, transferable_wei, locked_wei, deadline_unix) -> dict:
    reference_id_bytes32 = _reference_id_to_bytes32(reference_id)
    if chain == "BNB":
        chain_id = bnb_chain_id()
        signature = eip712_signer.sign_bnb_claim(
            user_address=wallet["address"], amount_wei=amount_wei,
            reference_id_bytes32=reference_id_bytes32, deadline_unix=deadline_unix,
            chain_id=chain_id, verifying_contract=chain_cfg["xera_distributor_address"],
        )
        return {
            "chain": "BNB", "reference_id": reference_id, "contract_address": chain_cfg["xera_distributor_address"],
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
        "chain": "TON", "contract_address": chain_cfg["xera_distributor_address"], "query_id": str(query_id),
        "user": wallet["address"], "amount_wei": str(amount_wei), "reference_id": reference_id,
        "reference_id_uint256": str(ton_result["reference_id_uint256"]), "deadline": deadline_unix,
        "signature": "0x" + ton_result["signature_hex"],
        "transferable_wei": str(transferable_wei), "locked_wei": str(locked_wei),
    }


def sign_amount_claim(user_id: int, chain: str, amount_raw) -> dict:
    """
    Move `amount_raw` XERA of the user's claimable balance to their verified
    wallet on `chain`. Returns the signed claim to submit on-chain.

    Order matters: validate input -> verified wallet -> chain enabled -> atomic
    reservation (this is where the balance is debited and the 75M cap checked)
    -> sign. If signing fails AFTER the reservation, the reservation is marked
    FAILED immediately so the funds are never stuck behind a signature that was
    never produced; the user can simply retry.
    """
    chain = chain.upper()
    if chain not in ("BNB", "TON"):
        raise ClaimError("unsupported_chain")
    amount = parse_claim_amount(amount_raw)

    wallet = _get_verified_wallet(user_id, chain)
    try:
        chain_cfg = require_onchain_enabled(chain)
    except ChainConfigError as e:
        raise ClaimError(str(e))

    transferable, locked = split_claim_amount(amount)
    amount_wei = _decimal_to_wei(amount)
    transferable_wei = (amount_wei * 2500) // 10000
    locked_wei = amount_wei - transferable_wei

    reference_id = f"claim-{uuid.uuid4()}"
    deadline_unix = int(time.time()) + _CLAIM_SIGNATURE_TTL_SECONDS

    try:
        supabase.rpc("xera_reserve_onchain_claim_amount", {
            "p_reference_id": reference_id,
            "p_user_id": user_id,
            "p_chain": chain,
            "p_wallet_address": wallet["address"],
            "p_amount": str(amount),
            "p_transferable_amount": str(transferable),
            "p_locked_amount": str(locked),
            "p_contract_address": chain_cfg["xera_distributor_address"],
            "p_deadline": _iso_from_unix(deadline_unix),
        }).execute()
    except Exception as e:
        msg = str(e)
        for code in ("insufficient_claimable_balance", "global_mining_allocation_exceeded",
                     "wallet_not_active", "wallet_not_found", "invalid_amount", "invalid_split"):
            if code in msg:
                raise ClaimError(code)
        raise

    try:
        return _build_signed_claim(chain, wallet, chain_cfg, reference_id, amount_wei,
                                   transferable_wei, locked_wei, deadline_unix)
    except Exception:
        try:
            supabase.rpc("xera_mark_onchain_claim_failed", {"p_reference_id": reference_id}).execute()
        except Exception:
            pass  # the stale-claim sweep will expire it; funds stay held for a retry either way
        raise ClaimError("claim_signer_not_configured")


def get_claim_overview(user_id: int) -> dict:
    """What the claim screen needs: how much can be moved, and the user's recent claims."""
    # An abandoned SIGNED claim (wallet popup closed, tab left) must become EXPIRED
    # once its signature can no longer be executed, or it would sit "in progress"
    # forever and never be retryable. Nothing else schedules this sweep.
    _sweep_expired_claims()
    bal_res = supabase.rpc("xera_claimable_balance", {"p_user_id": user_id}).execute()
    bal = first_row(bal_res.data) or {}

    claims_res = (
        supabase.table("xera_onchain_claims")
        .select("reference_id,chain,wallet_address,claimed_amount,transferable_amount,locked_amount,"
                "status,transaction_hash,signature_deadline,created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(25)
        .execute()
    )
    return {
        "balance": float(bal.get("cached_balance") or 0),
        "claimable": float(bal.get("claimable") or 0),
        "min_amount": float(min_claim_amount()),
        "transferable_percent": 25,
        "locked_percent": 75,
        "claims": claims_res.data or [],
    }


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
        return first_row(confirmed.data) or row

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
        return first_row(confirmed.data) or row

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
    if row["status"] in ("SIGNED", "SUBMITTED"):
        _sweep_expired_claims()
        refreshed = supabase.table("xera_onchain_claims").select("*").eq("reference_id", reference_id).limit(1).execute()
        if refreshed.data:
            row = refreshed.data[0]
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
        chain_id = bnb_chain_id()
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
