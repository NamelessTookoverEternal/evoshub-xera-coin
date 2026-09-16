"""
XERA blockchain-layer configuration.

Section 7 of the brief is explicit: the ClaimSigner private key must be
kept separate from ordinary application secrets (XERA_TOKEN_SECRET,
ADMIN_TOKEN_SECRET, SUPABASE_SERVICE_KEY, ...). It lives in its own env
var, XERA_CLAIM_SIGNER_PRIVATE_KEY, read only by chain/eip712_signer.py —
nothing else in the codebase touches it. In production this should be
backed by a KMS/HSM-held key rather than a raw env var; the env var path
here is the local/staging fallback, clearly called out as such.

Chain-specific contract addresses and per-chain supply caps live in
Supabase (xera_chain_config), not hard-coded, for the same reason the rest
of XERA's tunables do (see xera/config.py) — an admin updating a deployed
contract address takes effect on the next request, not after a redeploy.
"""

from main import supabase


class ChainConfigError(Exception):
    pass


def get_chain_config(chain: str) -> dict:
    chain = chain.upper()
    if chain not in ("BNB", "TON"):
        raise ChainConfigError("invalid_chain")
    res = supabase.table("xera_chain_config").select("*").eq("chain", chain).limit(1).execute()
    if not res.data:
        raise ChainConfigError(f"xera_chain_config row missing for {chain} — run the blockchain migration.")
    return res.data[0]


def require_onchain_enabled(chain: str) -> dict:
    cfg = get_chain_config(chain)
    if not cfg.get("onchain_enabled"):
        raise ChainConfigError("onchain_disabled")
    if not cfg.get("xera_distributor_address"):
        raise ChainConfigError("distributor_not_configured")
    return cfg


def claim_signer_ton_key() -> str:
    """
    Ed25519 signing seed (hex) for TON claim authorization — deliberately
    a SEPARATE secret from XERA_CLAIM_SIGNER_PRIVATE_KEY (the BNB
    secp256k1 key). A leak of one key must never expose the other, and
    the two chains should be rotatable independently (see section 7 and
    XeraMiningDistributor.tact's RotateSigner).
    """
    import os
    key = os.getenv("XERA_CLAIM_SIGNER_TON_SEED", "")
    if not key:
        raise RuntimeError(
            "XERA_CLAIM_SIGNER_TON_SEED not configured — this must be set separately "
            "from XERA_CLAIM_SIGNER_PRIVATE_KEY (the BNB key). See BLOCKCHAIN_INTEGRATION.md."
        )
    return key
