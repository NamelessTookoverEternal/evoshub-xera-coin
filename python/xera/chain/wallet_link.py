"""
Section 8: external wallet linking, without replacing the internal
xera_wallets accounting wallet.

Two ways a wallet can be associated with a XERA account, kept strictly apart:

  * CONNECTED (connection_method='wallet', status='VERIFIED')
    Ownership is proven cryptographically — nonce + signature (BNB) or the
    TON Connect ton_proof (TON) — then recorded atomically (including the
    wallet-change cooldown) via xera_link_external_wallet.

  * MANUAL (connection_method='manual', status='PENDING')
    A typed PUBLIC address. Validated and normalised, attached to the
    authenticated account, and clearly marked unverified. It proves nothing
    about ownership and can NEVER settle a claim: claims.py only reads
    status='VERIFIED', and a DB CHECK constraint forbids a manual row from
    ever being VERIFIED.

Nothing here accepts, requests or stores a seed phrase, private key or
wallet password.
"""

import os

from main import supabase
from xera.chain.addresses import (
    AddressError, normalize_address, normalize_ton_address, ton_display,
)
from xera.chain.nonces import issue_nonce, consume_nonce, NonceError
from xera.chain.bnb_verify import build_link_message, verify_bnb_signature
from xera.chain.ton_verify import verify_ton_ownership

_WALLET_CHANGE_COOLDOWN_SECONDS = int(os.getenv("XERA_WALLET_CHANGE_COOLDOWN_SECONDS", str(24 * 60 * 60)))

# A TON nonce is issued BEFORE the wallet is connected, so the real address
# isn't known yet. The nonce is bound to this fixed placeholder instead of a
# client-supplied string; the actual address is bound by the ton_proof itself
# (the signed message embeds workchain + address hash, and the wallet's
# StateInit must hash to that address — see ton_verify.verify_ton_ownership).
_TON_NONCE_ADDRESS = "ton-proof-pending"


class WalletLinkError(Exception):
    pass


def _normalize(chain: str, address: str) -> str:
    try:
        return normalize_address(chain, address)
    except AddressError as e:
        raise WalletLinkError(str(e))


def start_link(user_id: int, chain: str, address: str) -> dict:
    chain = chain.upper()
    if chain not in ("BNB", "TON"):
        raise WalletLinkError("invalid_chain")

    if chain == "BNB":
        address = _normalize(chain, address)
        row = issue_nonce(user_id, chain, address)
        return {
            "nonce": row["nonce"], "expires_at": row["expires_at"], "chain": chain, "address": address,
            "message_to_sign": build_link_message(row["nonce"], address),
        }

    row = issue_nonce(user_id, chain, _TON_NONCE_ADDRESS)
    return {
        "nonce": row["nonce"], "expires_at": row["expires_at"], "chain": chain,
        "ton_proof_payload": row["nonce"],  # passed to TonConnect's connectRequest as `payload`
    }


def verify_and_link(user_id: int, chain: str, address: str, nonce: str, **proof) -> dict:
    chain = chain.upper()
    if chain not in ("BNB", "TON"):
        raise WalletLinkError("invalid_chain")

    address = _normalize(chain, address)
    nonce_address = address if chain == "BNB" else _TON_NONCE_ADDRESS

    try:
        consume_nonce(user_id, chain, nonce_address, nonce)
    except NonceError as e:
        raise WalletLinkError(str(e))

    if chain == "BNB":
        signature = proof.get("signature")
        if not signature or not verify_bnb_signature(address=address, nonce=nonce, signature=signature):
            raise WalletLinkError("invalid_signature")
    else:
        ok = verify_ton_ownership(
            address=address,
            domain=proof.get("domain") or "",
            timestamp=proof.get("timestamp") or 0,
            payload=nonce,
            signature_b64=proof.get("signature") or "",
            wallet_public_key_hex=proof.get("public_key") or "",
            wallet_state_init_b64=proof.get("state_init") or "",
        )
        if not ok:
            raise WalletLinkError("invalid_proof")

    try:
        res = supabase.rpc("xera_link_external_wallet", {
            "p_user_id": user_id,
            "p_chain": chain,
            "p_address": address,
            "p_cooldown_seconds": _WALLET_CHANGE_COOLDOWN_SECONDS,
        }).execute()
    except Exception as e:
        msg = str(e)
        for code in ("wallet_change_cooldown_active", "address_already_linked", "invalid_chain"):
            if code in msg:
                raise WalletLinkError(code)
        raise

    return _shape(res.data[0]) if res.data else {}


# ------------------------------------------------------------
# Manual (typed, UNVERIFIED) addresses
# ------------------------------------------------------------

def set_manual_wallet(user_id: int, chain: str, address: str) -> dict:
    chain = chain.upper()
    if chain not in ("BNB", "TON"):
        raise WalletLinkError("invalid_chain")
    address = _normalize(chain, address)

    try:
        res = supabase.rpc("xera_set_manual_wallet", {
            "p_user_id": user_id, "p_chain": chain, "p_address": address,
        }).execute()
    except Exception as e:
        msg = str(e)
        for code in ("verified_wallet_exists", "manual_wallet_conflict", "invalid_chain"):
            if code in msg:
                raise WalletLinkError(code)
        raise

    return _shape(res.data[0]) if res.data else {}


def remove_wallet(user_id: int, chain: str) -> dict:
    """Disconnect (verified) or remove (manual) the user's active wallet for a chain."""
    chain = chain.upper()
    if chain not in ("BNB", "TON"):
        raise WalletLinkError("invalid_chain")
    try:
        res = supabase.rpc("xera_remove_external_wallet", {"p_user_id": user_id, "p_chain": chain}).execute()
    except Exception as e:
        msg = str(e)
        for code in ("wallet_not_found", "invalid_chain"):
            if code in msg:
                raise WalletLinkError(code)
        raise
    return _shape(res.data[0]) if res.data else {}


# ------------------------------------------------------------
# Reads — always scoped to the authenticated user_id
# ------------------------------------------------------------

def _shape(row: dict) -> dict:
    method = row.get("connection_method") or "wallet"
    verified = row.get("status") == "VERIFIED" and method == "wallet"
    chain = row["chain"]
    return {
        "chain": chain,
        "address": row["address"],
        "display_address": ton_display(row["address"]) if chain == "TON" else row["address"],
        "status": row.get("status"),
        "connection_method": method,
        "verified": verified,
        "verified_at": row.get("verified_at"),
        "linked_at": row.get("linked_at"),
    }


def get_wallets(user_id: int) -> list[dict]:
    """The user's active wallets: connected (verified) and manual (unverified)."""
    cols = "chain, address, status, connection_method, verified_at, linked_at"
    try:
        res = (
            supabase.table("xera_external_wallets").select(cols)
            .eq("user_id", user_id).in_("status", ["VERIFIED", "PENDING"]).execute()
        )
    except Exception:
        # connection_method migration (20261003) not applied yet — behave as
        # before: every active row is a verified, connected wallet.
        res = (
            supabase.table("xera_external_wallets")
            .select("chain, address, status, verified_at, linked_at")
            .eq("user_id", user_id).eq("status", "VERIFIED").execute()
        )
    return [_shape(r) for r in (res.data or [])]


def get_linked_wallets(user_id: int) -> list[dict]:
    """VERIFIED wallets only — what claim eligibility and vesting status use."""
    res = (
        supabase.table("xera_external_wallets")
        .select("chain, address, status, verified_at, linked_at")
        .eq("user_id", user_id)
        .eq("status", "VERIFIED")
        .execute()
    )
    return res.data or []
