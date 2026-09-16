"""
Section 16: "Do not trust a client-submitted transaction as proof without
independently validating the transaction/event." This module fetches the
transaction receipt directly from a BNB RPC node and checks the
`ClaimSettled` event log itself — the client only ever tells us a tx hash;
everything else (user, referenceId, amounts, contract address, success
status) is re-derived from the chain.
"""

import os

from eth_abi import decode as abi_decode
from eth_utils import keccak, to_checksum_address
from web3 import Web3

_CLAIM_SETTLED_SIG = keccak(text="ClaimSettled(address,bytes32,uint256,uint256,uint256)")


class IndexerError(Exception):
    pass


def _bnb_rpc_url() -> str:
    url = os.getenv("BNB_RPC_URL", "")
    if not url:
        raise IndexerError("bnb_rpc_not_configured")
    return url


def verify_bnb_claim_tx(*, tx_hash: str, distributor_address: str, expected_user: str,
                         expected_reference_id_bytes32: bytes, expected_total_amount_wei: int) -> dict:
    """
    Returns {"block_number": int, "transferable": int, "locked": int} on
    success. Raises IndexerError with a short machine-readable code on any
    mismatch or failure — the caller (routes_chain.py) maps these to HTTP
    responses and never marks a claim CONFIRMED unless this returns cleanly.
    """
    w3 = Web3(Web3.HTTPProvider(_bnb_rpc_url()))

    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
    except Exception:
        raise IndexerError("transaction_not_found")

    if receipt is None:
        raise IndexerError("transaction_not_found")
    if receipt.status != 1:
        raise IndexerError("transaction_reverted")

    distributor_checksum = to_checksum_address(distributor_address)
    user_checksum = to_checksum_address(expected_user)

    for log in receipt.logs:
        if to_checksum_address(log.address) != distributor_checksum:
            continue
        topics = log.topics
        if len(topics) < 3 or bytes(topics[0]) != _CLAIM_SETTLED_SIG:
            continue

        log_user = to_checksum_address("0x" + bytes(topics[1])[-20:].hex())
        log_reference_id = bytes(topics[2])

        if log_user != user_checksum:
            continue
        if log_reference_id != expected_reference_id_bytes32:
            continue

        total_amount, transferable, locked = abi_decode(["uint256", "uint256", "uint256"], bytes(log.data))

        if total_amount != expected_total_amount_wei:
            raise IndexerError("amount_mismatch")

        return {
            "block_number": receipt.blockNumber,
            "transferable": transferable,
            "locked": locked,
        }

    raise IndexerError("claim_settled_event_not_found")


# ================= TON =================
#
# TON has no EVM-style event logs — confirmation instead re-parses the
# ACTUAL in-message body of the transaction (fetched independently from a
# TON HTTP API, never trusting client-supplied field values) using the
# exact same cell layout python/xera/chain/ton_claim_signer.py signs
# against, and checks the transaction's compute/action phases succeeded.
#
# NOT live-tested against a real TON RPC endpoint in this sandbox (no
# network path to a TON API host here) — same caveat that already applied
# to the pre-existing BNB indexer before any live testnet run. The cell-
# parsing logic itself IS exercised for real: python/tests/test_ton_claim_signer.py
# and the TON sandbox test both build/parse this exact structure.

import requests as _requests
from pytoniq_core import Cell as _TonCell, Address as _TonAddress

from xera.chain.ton_claim_signer import reference_id_to_uint256 as _ton_ref_id_to_uint256


def _ton_api_base() -> str:
    url = os.getenv("TON_API_BASE_URL", "")
    if not url:
        raise IndexerError("ton_rpc_not_configured")
    return url.rstrip("/")


def _ton_api_key() -> str | None:
    return os.getenv("TON_API_KEY") or None


def verify_ton_claim_tx(*, tx_hash: str, distributor_address: str, expected_user_address: str,
                         expected_reference_id: str, expected_total_amount_nano: int) -> dict:
    """
    Fetches the transaction by hash for `distributor_address` from a TON
    HTTP API (TON Center-compatible `/getTransactions` shape — set
    TON_API_BASE_URL, e.g. https://testnet.toncenter.com/api/v2 or
    https://toncenter.com/api/v2 for mainnet), re-parses its in-message
    body as a Claim, and verifies every field independently. Returns
    {"block_number": <logical time, used the same way BNB's block_number
    is used — as an opaque ordering reference, not a real EVM block>}.
    """
    headers = {"X-API-Key": _ton_api_key()} if _ton_api_key() else {}
    try:
        resp = _requests.get(
            f"{_ton_api_base()}/getTransactions",
            params={"address": distributor_address, "hash": tx_hash, "limit": 1},
            headers=headers, timeout=15,
        )
        payload = resp.json()
    except Exception:
        raise IndexerError("ton_rpc_request_failed")

    if not payload.get("ok") or not payload.get("result"):
        raise IndexerError("transaction_not_found")

    tx = payload["result"][0]

    # Compute/action phase success — TON's equivalent of an EVM tx's
    # `status == 1`. A transaction that bounced or failed at any phase
    # must never be treated as a successful settlement.
    desc = tx.get("description", {})
    compute_ok = desc.get("compute_ph", {}).get("success", False)
    action_ok = desc.get("action", {}).get("success", True)  # some responses omit action_ph on messages with no outbound actions
    if not compute_ok or not action_ok:
        raise IndexerError("transaction_reverted")

    in_msg = tx.get("in_msg", {})
    in_msg_body_b64 = in_msg.get("msg_data", {}).get("body") or in_msg.get("message")
    if not in_msg_body_b64:
        raise IndexerError("claim_message_not_found")

    try:
        cell = _TonCell.one_from_boc(in_msg_body_b64)
        slice_ = cell.begin_parse()
        opcode = slice_.load_uint(32)
        if opcode != 0x2000:
            raise IndexerError("not_a_claim_message")
        query_id = slice_.load_uint(64)
        data_cell = slice_.load_ref()
        data_slice = data_cell.begin_parse()
        user = data_slice.load_address()
        amount = data_slice.load_coins()
        reference_id_uint256 = data_slice.load_uint(256)
        deadline = data_slice.load_uint(64)
    except IndexerError:
        raise
    except Exception:
        raise IndexerError("claim_message_parse_failed")

    if str(user) != str(_TonAddress(expected_user_address)):
        raise IndexerError("user_mismatch")
    if amount != expected_total_amount_nano:
        raise IndexerError("amount_mismatch")
    if reference_id_uint256 != _ton_ref_id_to_uint256(expected_reference_id):
        raise IndexerError("reference_id_mismatch")

    return {"block_number": tx.get("transaction_id", {}).get("lt"), "query_id": query_id, "deadline": deadline}


_LEGACY_CLAIMED_SIG = keccak(text="LegacyClaimed(uint256,address,uint256)")


def verify_bnb_legacy_claim_tx(*, tx_hash: str, migration_address: str, expected_leaf_index: int,
                                expected_account: str, expected_amount_wei: int) -> dict:
    """
    Same independent-verification pattern as verify_bnb_claim_tx, for
    XeraMigrationClaim's one-time legacy-balance claim (section 10/16).
    """
    w3 = Web3(Web3.HTTPProvider(_bnb_rpc_url()))

    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
    except Exception:
        raise IndexerError("transaction_not_found")

    if receipt is None:
        raise IndexerError("transaction_not_found")
    if receipt.status != 1:
        raise IndexerError("transaction_reverted")

    migration_checksum = to_checksum_address(migration_address)
    account_checksum = to_checksum_address(expected_account)

    for log in receipt.logs:
        if to_checksum_address(log.address) != migration_checksum:
            continue
        topics = log.topics
        if len(topics) < 3 or bytes(topics[0]) != _LEGACY_CLAIMED_SIG:
            continue

        log_leaf_index = int.from_bytes(bytes(topics[1]), "big")
        log_account = to_checksum_address("0x" + bytes(topics[2])[-20:].hex())

        if log_leaf_index != expected_leaf_index or log_account != account_checksum:
            continue

        (amount,) = abi_decode(["uint256"], bytes(log.data))
        if amount != expected_amount_wei:
            raise IndexerError("amount_mismatch")

        return {"block_number": receipt.blockNumber}

    raise IndexerError("legacy_claim_event_not_found")


_VESTING_ABI_FRAGMENT = [
    {"name": "releasable", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "user", "type": "address"}], "outputs": [{"type": "uint256"}]},
    {"name": "lockedRemaining", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "user", "type": "address"}], "outputs": [{"type": "uint256"}]},
]


def get_vesting_status(*, vesting_address: str, user_address: str) -> dict:
    """Read-only view call — never trusted for settlement, only for display."""
    w3 = Web3(Web3.HTTPProvider(_bnb_rpc_url()))
    contract = w3.eth.contract(address=to_checksum_address(vesting_address), abi=_VESTING_ABI_FRAGMENT)
    try:
        releasable = contract.functions.releasable(to_checksum_address(user_address)).call()
        locked_remaining = contract.functions.lockedRemaining(to_checksum_address(user_address)).call()
    except Exception:
        raise IndexerError("vesting_read_failed")
    return {"releasable_wei": str(releasable), "locked_remaining_wei": str(locked_remaining)}
