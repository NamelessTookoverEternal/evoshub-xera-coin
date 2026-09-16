"""
Short-lived nonces for wallet-link ownership proofs (BNB signature / TON
proof payload). A nonce is single-use: `consumed_at` is set the moment
verification succeeds, inside the same request that links the wallet, so a
captured nonce+signature pair can't be replayed to re-link later.
"""

import secrets
from datetime import datetime, timedelta, timezone

from main import supabase

_NONCE_TTL_SECONDS = 5 * 60


class NonceError(Exception):
    pass


def issue_nonce(user_id: int, chain: str, address: str) -> dict:
    nonce = secrets.token_urlsafe(24)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=_NONCE_TTL_SECONDS)).isoformat()
    row = {
        "user_id": user_id,
        "chain": chain.upper(),
        "address": address,
        "nonce": nonce,
        "expires_at": expires_at,
    }
    res = supabase.table("xera_wallet_link_nonces").insert(row).execute()
    return res.data[0]


def consume_nonce(user_id: int, chain: str, address: str, nonce: str) -> dict:
    """
    Atomically consumes a nonce. Every binding check (user, chain,
    address, expiry, not-already-consumed) happens inside a single
    conditional UPDATE in Postgres — see xera_consume_wallet_nonce in
    supabase/migrations/20260914_xera_blockchain_hardening.sql.

    This replaced an earlier SELECT-then-UPDATE implementation, which had
    a TOCTOU race: two concurrent requests presenting the same nonce could
    both pass the SELECT before either wrote consumed_at, allowing one
    captured nonce+signature pair to be replayed.
    """
    try:
        res = supabase.rpc("xera_consume_wallet_nonce", {
            "p_user_id": user_id,
            "p_chain": chain.upper(),
            "p_address": address,
            "p_nonce": nonce,
        }).execute()
    except Exception as e:
        message = str(e)
        for code in ("nonce_already_consumed", "nonce_address_mismatch", "nonce_expired", "nonce_not_found"):
            if code in message:
                raise NonceError(code)
        raise

    if not res.data:
        raise NonceError("nonce_not_found")
    return res.data[0] if isinstance(res.data, list) else res.data
