"""
BNB claim relayer: submits an already-signed claim to the distributor from a
server-held gas wallet, so the person claiming does not need a wallet browser.

Why this is safe to offer
  * XeraMiningDistributor.claim(user, amount, referenceId, deadline, signature)
    can be called by ANY address; the tokens always go to `user`, the address
    inside the signed message. The relayer only pays gas. It cannot redirect funds.
  * It is only ever called from an authenticated admin route with a claim that
    was just reserved and signed for that admin's own verified wallet.
  * Before spending any gas it simulates the call (estimate_gas). A claim that
    would revert (distributor not funded, vesting role missing, signature
    expired...) is reported and nothing is sent.
  * Gas price is capped (XERA_RELAYER_MAX_GAS_GWEI, default 10) and the relayer
    balance is checked first.

Key handling
  XERA_RELAYER_PRIVATE_KEY  the gas wallet. Keep it separate from the claim signer.
  Testnet convenience: if it is unset AND the chain is BNB testnet (chain id 97)
  AND XERA_RELAYER_USE_SIGNER=true, the claim signer key is reused as the gas
  wallet. That fallback is refused on any other chain id, so it can never run on
  mainnet. The key is only read here and never logged or returned.
"""
import logging
import os
import threading
import time

from eth_account import Account
from eth_utils import to_checksum_address
from web3 import Web3

from xera.chain.config import bnb_chain_id, ChainConfigError
from xera.chain.onchain_indexer import _bnb_rpc_url, IndexerError

logger = logging.getLogger(__name__)

TESTNET_CHAIN_IDS = {97}

_CLAIM_ABI = [{
    "type": "function", "name": "claim", "stateMutability": "nonpayable", "outputs": [],
    "inputs": [
        {"name": "user", "type": "address"},
        {"name": "amount", "type": "uint256"},
        {"name": "referenceId", "type": "bytes32"},
        {"name": "deadline", "type": "uint256"},
        {"name": "signature", "type": "bytes"},
    ],
}]

_send_lock = threading.Lock()      # one relayer wallet = one nonce sequence


class RelayerError(Exception):
    """Short machine-readable code; routes map it to an HTTP response."""


def _relayer_key() -> str:
    key = os.getenv("XERA_RELAYER_PRIVATE_KEY", "").strip()
    if key:
        return key
    use_signer = os.getenv("XERA_RELAYER_USE_SIGNER", "false").strip().lower() in ("1", "true", "yes")
    if use_signer:
        try:
            chain_id = bnb_chain_id()
        except ChainConfigError:
            raise RelayerError("relayer_not_configured")
        if chain_id not in TESTNET_CHAIN_IDS:
            raise RelayerError("relayer_not_configured")      # never reuse the signer key off testnet
        signer = os.getenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", "").strip()
        if signer:
            return signer
    raise RelayerError("relayer_not_configured")


def relayer_address() -> str:
    return Account.from_key(_relayer_key()).address


def _max_gas_price_wei() -> int:
    try:
        gwei = float(os.getenv("XERA_RELAYER_MAX_GAS_GWEI", "10"))
    except ValueError:
        gwei = 10.0
    return int(gwei * 10**9)


def _web3() -> Web3:
    try:
        return Web3(Web3.HTTPProvider(_bnb_rpc_url(), request_kwargs={"timeout": 20}))
    except IndexerError:
        raise RelayerError("bnb_rpc_not_configured")


def submit_bnb_claim(claim: dict) -> str:
    """Send the signed claim. Returns the transaction hash (0x...). Nothing is sent on any error."""
    if str(claim.get("chain", "BNB")).upper() != "BNB":
        raise RelayerError("unsupported_chain")
    account = Account.from_key(_relayer_key())
    w3 = _web3()

    try:
        if int(claim["chain_id"]) != int(w3.eth.chain_id):
            raise RelayerError("wrong_network")
        contract = w3.eth.contract(address=to_checksum_address(claim["contract_address"]), abi=_CLAIM_ABI)
        fn = contract.functions.claim(
            to_checksum_address(claim["user"]), int(claim["amount_wei"]),
            bytes.fromhex(claim["reference_id_hash"].removeprefix("0x")),
            int(claim["deadline"]), bytes.fromhex(claim["signature"].removeprefix("0x")),
        )
        try:
            gas = fn.estimate_gas({"from": account.address})     # simulation: a revert raises here, no gas spent
        except Exception as exc:
            logger.warning("XERA RELAYER: claim would revert (%s)", str(exc)[:200])
            raise RelayerError("claim_would_revert")

        gas_price = int(w3.eth.gas_price)
        if gas_price > _max_gas_price_wei():
            raise RelayerError("gas_price_too_high")
        gas_limit = int(gas * 1.25)
        if int(w3.eth.get_balance(account.address)) < gas_limit * gas_price:
            raise RelayerError("relayer_unfunded")

        with _send_lock:
            tx = fn.build_transaction({
                "from": account.address, "chainId": int(claim["chain_id"]), "gas": gas_limit, "gasPrice": gas_price,
                "nonce": w3.eth.get_transaction_count(account.address, "pending"),
            })
            signed = account.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
            tx_hash = w3.eth.send_raw_transaction(raw)
    except RelayerError:
        raise
    except Exception as exc:
        logger.error("XERA RELAYER: submit failed (%s)", str(exc)[:200])
        raise RelayerError("relay_failed")

    h = tx_hash.hex()
    return h if h.startswith("0x") else "0x" + h


def wait_for_receipt(tx_hash: str, timeout_seconds: int = 45) -> bool:
    """True once the transaction is mined successfully; False on timeout or revert."""
    w3 = _web3()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            receipt = None
        if receipt is not None:
            return receipt.status == 1
        time.sleep(2)
    return False
