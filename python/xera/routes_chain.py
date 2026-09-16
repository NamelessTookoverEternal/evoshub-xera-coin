"""
XERA blockchain integration API — mounted in main.py as:

    from xera.routes_chain import router as xera_chain_router
    app.include_router(xera_chain_router, prefix="/api/xera", tags=["xera-chain"])

Every route requires the same XERA session token as routes.py (section 16:
"authenticate the user" is step 1 of every claim/link flow). None of these
trust a user_id from the request body.
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from main import limiter
from xera.user_auth import verify_user_token, XeraTokenInvalid
from xera.chain.wallet_link import start_link, verify_and_link, get_linked_wallets, WalletLinkError
from xera.chain.claims import sign_claim, confirm_claim, retry_claim, ClaimError
from xera.chain import migration as legacy_migration
from xera.chain.migration import MigrationClaimError
from xera.chain.config import get_chain_config, ChainConfigError
from xera.chain.onchain_indexer import get_vesting_status, IndexerError

logger = logging.getLogger(__name__)
router = APIRouter()


def _current_user_id(authorization: str) -> int:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_user_token(token)
    except XeraTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")


_WALLET_ERROR_HTTP = {
    "invalid_chain":               (400, "Unsupported chain."),
    "nonce_not_found":              (400, "Link request not found or already used."),
    "nonce_already_consumed":       (400, "This link request has already been used — please start again."),
    "nonce_address_mismatch":       (400, "Signed address does not match the requested wallet."),
    "nonce_expired":                (400, "Link request expired — please try again."),
    "invalid_signature":            (400, "Wallet signature could not be verified."),
    "invalid_proof":                (400, "Wallet proof could not be verified."),
    "wallet_change_cooldown_active": (429, "You recently changed this wallet — please try again later."),
    "address_already_linked":       (409, "This address is already linked to another account."),
}

_CLAIM_ERROR_HTTP = {
    "entitlement_not_found":            (404, "No matching mining entitlement found."),
    "already_claimed_or_reserved":      (409, "This entitlement has already been claimed."),
    "no_verified_wallet":               (400, "Link and verify a wallet for this chain first."),
    "onchain_disabled":                 (403, "On-chain claims are currently disabled."),
    "distributor_not_configured":       (503, "This chain isn't fully configured yet."),
    "claim_signer_not_configured":      (503, "Claim signing is temporarily unavailable."),
    "global_mining_allocation_exceeded": (409, "The global mining allocation has been fully claimed."),
    "claim_not_retryable":              (409, "This claim isn't in a retryable state."),
    "unsupported_chain":                (400, "Unsupported chain."),
    "claim_not_found":                  (404, "Claim not found."),
    "not_your_claim":                   (403, "This claim does not belong to you."),
    "transaction_not_found":            (404, "Transaction not found on-chain yet — it may still be pending."),
    "transaction_reverted":             (409, "The on-chain transaction failed."),
    "amount_mismatch":                  (409, "On-chain amount does not match the signed entitlement."),
    "user_mismatch":                    (409, "On-chain recipient does not match your linked wallet."),
    "reference_id_mismatch":            (409, "On-chain reference does not match this entitlement."),
    "claim_settled_event_not_found":    (409, "Could not find a matching settlement event in this transaction."),
    "claim_message_not_found":          (409, "Could not find a claim message in this transaction."),
    "claim_message_parse_failed":       (409, "Could not read the claim message in this transaction."),
    "not_a_claim_message":              (409, "That transaction is not a XERA mining claim."),
    "bnb_rpc_not_configured":           (503, "Blockchain confirmation is temporarily unavailable."),
    "ton_rpc_not_configured":           (503, "TON confirmation is temporarily unavailable."),
    "ton_rpc_request_failed":           (503, "Could not reach the TON network to confirm this claim."),
}

_MIGRATION_ERROR_HTTP = {
    "no_legacy_balance":        (404, "No legacy balance found for this account."),
    "already_claimed":         (409, "Your legacy balance has already been claimed."),
    "proof_not_generated":     (503, "Legacy migration proofs aren't published yet."),
    "migration_not_configured": (503, "Legacy migration isn't configured for this chain yet."),
    "no_verified_wallet":      (400, "Link and verify a wallet for this chain first."),
    "invalid_chain":           (400, "Unsupported chain."),
    "transaction_not_found":   (404, "Transaction not found on-chain yet — it may still be pending."),
    "transaction_reverted":    (409, "The on-chain transaction failed."),
    "amount_mismatch":         (409, "On-chain amount does not match your legacy balance."),
    "legacy_claim_event_not_found": (409, "Could not find a matching claim event in this transaction."),
    "migration_chain_not_supported": (400, "Legacy migration is available on BNB only."),
}


# ------------------------------------------------------------
# WALLET LINKING
# ------------------------------------------------------------

class WalletLinkNonceRequest(BaseModel):
    chain: str = Field(..., pattern="^(BNB|TON|bnb|ton)$")
    address: str = Field(..., min_length=3, max_length=128)


@router.post("/wallet/link/nonce")
@limiter.limit("10/minute")
def wallet_link_nonce(request: Request, data: WalletLinkNonceRequest, authorization: str = Header(default="")):
    user_id = _current_user_id(authorization)
    try:
        result = start_link(user_id, data.chain, data.address)
    except WalletLinkError as e:
        status, message = _WALLET_ERROR_HTTP.get(str(e), (400, "Could not start wallet link."))
        raise HTTPException(status_code=status, detail=message)
    return {"status": "ok", **result}


class WalletLinkVerifyRequest(BaseModel):
    """
    Single request shape covering both chains — BNB only ever needs
    signature; TON additionally needs domain/timestamp/public_key (the
    rest of its ton_proof payload). Kept as one Pydantic model rather than
    a union body: FastAPI can't discriminate a bare Union[...] request body
    without an explicit discriminator field, and chain-specific validation
    (which fields are actually required) already happens in
    xera.chain.wallet_link / xera.chain.ton_verify — this model only
    handles wire-level shape and length limits.
    """
    chain: str = Field(..., pattern="^(BNB|TON|bnb|ton)$")
    address: str = Field(..., min_length=3, max_length=128)
    nonce: str = Field(..., min_length=1, max_length=128)
    signature: str = Field(..., min_length=1, max_length=512)
    # TON-only fields — optional here, required in practice for chain=TON
    # (xera.chain.ton_verify.verify_ton_proof fails closed on missing values).
    domain: str | None = Field(default=None, max_length=256)
    timestamp: int | None = Field(default=None, gt=0)
    public_key: str | None = Field(default=None, max_length=128)


@router.post("/wallet/link/verify")
@limiter.limit("10/minute")
def wallet_link_verify(request: Request, data: WalletLinkVerifyRequest, authorization: str = Header(default="")):
    user_id = _current_user_id(authorization)
    proof = data.model_dump(exclude={"chain", "address", "nonce"})
    try:
        result = verify_and_link(user_id, data.chain, data.address, data.nonce, **proof)
    except WalletLinkError as e:
        status, message = _WALLET_ERROR_HTTP.get(str(e), (400, "Could not verify wallet."))
        raise HTTPException(status_code=status, detail=message)
    return {"status": "ok", "wallet": result}


@router.get("/wallet/linked")
@limiter.limit("30/minute")
def wallet_linked(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(authorization)
    return {"status": "ok", "wallets": get_linked_wallets(user_id)}


# ------------------------------------------------------------
# CLAIM SIGNING / CONFIRMATION
# ------------------------------------------------------------

class ClaimSignRequest(BaseModel):
    reference_id: str = Field(..., min_length=1, max_length=128)
    chain: str = Field(..., pattern="^(BNB|TON|bnb|ton)$")


@router.post("/claim/sign")
@limiter.limit("10/minute")
def claim_sign(request: Request, data: ClaimSignRequest, authorization: str = Header(default="")):
    user_id = _current_user_id(authorization)
    try:
        result = sign_claim(user_id, data.reference_id, data.chain)
    except ClaimError as e:
        status, message = _CLAIM_ERROR_HTTP.get(str(e), (400, "Could not sign claim."))
        raise HTTPException(status_code=status, detail=message)
    return {"status": "ok", "claim": result}


class ClaimConfirmRequest(BaseModel):
    reference_id: str = Field(..., min_length=1, max_length=128)
    transaction_hash: str = Field(..., min_length=1, max_length=128)


@router.post("/claim/confirm")
@limiter.limit("10/minute")
def claim_confirm(request: Request, data: ClaimConfirmRequest, authorization: str = Header(default="")):
    user_id = _current_user_id(authorization)
    try:
        result = confirm_claim(user_id, data.reference_id, data.transaction_hash)
    except ClaimError as e:
        status, message = _CLAIM_ERROR_HTTP.get(str(e), (400, "Could not confirm claim."))
        raise HTTPException(status_code=status, detail=message)
    return {"status": "ok", "claim": result}


class ClaimRetryRequest(BaseModel):
    reference_id: str = Field(..., min_length=1, max_length=128)
    chain: str = Field(..., pattern="^(BNB|TON|bnb|ton)$")


@router.post("/claim/retry")
@limiter.limit("5/minute")
def claim_retry(request: Request, data: ClaimRetryRequest, authorization: str = Header(default="")):
    """
    Recovery for a FAILED/EXPIRED claim. This re-signs the SAME
    reservation row rather than creating a new one — a reference_id
    still gets exactly one successful settlement across BNB + TON
    combined (see xera_retry_onchain_claim). The chain may differ from
    the original attempt, which is why this exists at all: a user whose
    BNB transaction failed shouldn't be permanently stranded.
    """
    user_id = _current_user_id(authorization)
    try:
        result = retry_claim(user_id, data.reference_id, data.chain)
    except ClaimError as e:
        status, message = _CLAIM_ERROR_HTTP.get(str(e), (400, "Could not retry claim."))
        raise HTTPException(status_code=status, detail=message)
    return {"status": "ok", "claim": result}

@router.get("/onchain/status")
@limiter.limit("30/minute")
def onchain_status(request: Request, chain: str = "BNB", authorization: str = Header(default="")):
    user_id = _current_user_id(authorization)
    chain = chain.upper()

    wallets = get_linked_wallets(user_id)
    wallet = next((w for w in wallets if w["chain"] == chain), None)

    vesting = None
    if wallet:
        try:
            chain_cfg = get_chain_config(chain)
            if chain_cfg.get("xera_vesting_address"):
                vesting = get_vesting_status(
                    vesting_address=chain_cfg["xera_vesting_address"],
                    user_address=wallet["address"],
                )
        except (ChainConfigError, IndexerError):
            vesting = None  # display-only — never blocks the response

    return {
        "status": "ok",
        "chain": chain,
        "linked_wallet": wallet,
        "vesting": vesting,
    }


# ------------------------------------------------------------
# LEGACY MIGRATION CLAIM (section 10 — one-time, separate from mining claims)
# ------------------------------------------------------------

@router.get("/migration/status")
@limiter.limit("30/minute")
def migration_status(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(authorization)
    return {"status": "ok", "migration": legacy_migration.get_snapshot_status(user_id)}


class MigrationPrepareRequest(BaseModel):
    chain: str = Field(..., pattern="^(BNB|TON|bnb|ton)$")


@router.post("/migration/claim/prepare")
@limiter.limit("10/minute")
def migration_claim_prepare(request: Request, data: MigrationPrepareRequest, authorization: str = Header(default="")):
    user_id = _current_user_id(authorization)
    try:
        result = legacy_migration.prepare_claim(user_id, data.chain)
    except MigrationClaimError as e:
        status, message = _MIGRATION_ERROR_HTTP.get(str(e), (400, "Could not prepare legacy claim."))
        raise HTTPException(status_code=status, detail=message)
    return {"status": "ok", "claim": result}


class MigrationConfirmRequest(BaseModel):
    chain: str = Field(..., pattern="^(BNB|TON|bnb|ton)$")
    transaction_hash: str = Field(..., min_length=1, max_length=128)


@router.post("/migration/claim/confirm")
@limiter.limit("10/minute")
def migration_claim_confirm(request: Request, data: MigrationConfirmRequest, authorization: str = Header(default="")):
    user_id = _current_user_id(authorization)
    try:
        result = legacy_migration.confirm_claim(user_id, data.transaction_hash, data.chain)
    except MigrationClaimError as e:
        status, message = _MIGRATION_ERROR_HTTP.get(str(e), (400, "Could not confirm legacy claim."))
        raise HTTPException(status_code=status, detail=message)
    return {"status": "ok", "claim": result}
