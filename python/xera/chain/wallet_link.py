"""
Section 8: external wallet linking, without replacing the internal
xera_wallets accounting wallet. Verifies ownership via nonce + signature
(BNB) or TON Connect proof (TON), then records the link atomically
(including the wallet-change cooldown) via xera_link_external_wallet.
"""

import os

from main import supabase
from xera.chain.nonces import issue_nonce, consume_nonce, NonceError
from xera.chain.bnb_verify import build_link_message, verify_bnb_signature
from xera.chain.ton_verify import verify_ton_proof

_WALLET_CHANGE_COOLDOWN_SECONDS = int(os.getenv("XERA_WALLET_CHANGE_COOLDOWN_SECONDS", str(24 * 60 * 60)))


class WalletLinkError(Exception):
    pass


def start_link(user_id: int, chain: str, address: str) -> dict:
    chain = chain.upper()
    if chain not in ("BNB", "TON"):
        raise WalletLinkError("invalid_chain")

    row = issue_nonce(user_id, chain, address)
    result = {"nonce": row["nonce"], "expires_at": row["expires_at"], "chain": chain, "address": address}
    if chain == "BNB":
        result["message_to_sign"] = build_link_message(row["nonce"], address)
    else:
        result["ton_proof_payload"] = row["nonce"]  # passed to TonConnect's connectRequest as `payload`
    return result


def verify_and_link(user_id: int, chain: str, address: str, nonce: str, **proof) -> dict:
    chain = chain.upper()

    try:
        consume_nonce(user_id, chain, address, nonce)
    except NonceError as e:
        raise WalletLinkError(str(e))

    if chain == "BNB":
        signature = proof.get("signature")
        if not signature or not verify_bnb_signature(address=address, nonce=nonce, signature=signature):
            raise WalletLinkError("invalid_signature")
    else:
        ok = verify_ton_proof(
            address=address,
            domain=proof.get("domain", ""),
            timestamp=proof.get("timestamp", 0),
            payload=nonce,
            signature_b64=proof.get("signature", ""),
            wallet_public_key_hex=proof.get("public_key", ""),
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

    return res.data[0] if res.data else {}


def get_linked_wallets(user_id: int) -> list[dict]:
    res = (
        supabase.table("xera_external_wallets")
        .select("chain, address, status, verified_at, linked_at")
        .eq("user_id", user_id)
        .eq("status", "VERIFIED")
        .execute()
    )
    return res.data or []
