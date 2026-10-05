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


# ------------------------------------------------------------
# BNB network selection (testnet vs mainnet)
# ------------------------------------------------------------
#
# ONE source of truth for "which BNB chain does this deployment expect", used
# both when signing a claim (the EIP-712 domain's chainId) and when telling the
# frontend which network the user's wallet must be on. Previously claims.py
# read BNB_CHAIN_ID inline in two places; if the UI had its own idea of the
# chain the two could drift apart, so everything now reads from here.
#
#   XERA_BNB_CHAIN_ID  (preferred)   97 = BSC testnet, 56 = BSC mainnet
#   BNB_CHAIN_ID       (legacy alias, still honoured)
#
# Nothing here is a secret. The *server's* RPC URL (XERA_BNB_RPC_URL /
# BNB_RPC_URL, used by the indexer) is deliberately NEVER returned to the
# browser — it may embed a provider API key. The browser only gets a public
# RPC, used solely for the wallet's "add network" prompt.

_BNB_NETWORKS = {
    56: {
        "name": "BNB Smart Chain Mainnet",
        "short_name": "BSC Mainnet",
        "is_testnet": False,
        "public_rpc_url": "https://bsc-dataseed.binance.org",
        "explorer_url": "https://bscscan.com",
        "native_symbol": "BNB",
    },
    97: {
        "name": "BNB Smart Chain Testnet",
        "short_name": "BSC Testnet",
        "is_testnet": True,
        "public_rpc_url": "https://data-seed-prebsc-1-s1.binance.org:8545",
        "explorer_url": "https://testnet.bscscan.com",
        "native_symbol": "tBNB",
    },
}


def bnb_chain_id() -> int:
    import os
    raw = os.getenv("XERA_BNB_CHAIN_ID") or os.getenv("BNB_CHAIN_ID") or "97"
    try:
        return int(raw)
    except ValueError:
        raise ChainConfigError("invalid_bnb_chain_id")


def bnb_network_public() -> dict:
    import os
    chain_id = bnb_chain_id()
    meta = dict(_BNB_NETWORKS.get(chain_id) or {
        "name": f"EVM chain {chain_id}", "short_name": f"Chain {chain_id}", "is_testnet": True,
        "public_rpc_url": "", "explorer_url": "", "native_symbol": "BNB",
    })
    override = os.getenv("XERA_BNB_PUBLIC_RPC_URL", "").strip()
    if override:
        meta["public_rpc_url"] = override
    return {
        "chain_id": chain_id,
        "chain_id_hex": hex(chain_id),
        "supported_chain_ids": sorted(_BNB_NETWORKS),
        **meta,
    }
