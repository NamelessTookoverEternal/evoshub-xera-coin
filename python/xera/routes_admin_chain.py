"""
Admin on-chain pilot — mounted in main.py as:

    app.include_router(xera_admin_chain_router, prefix="/api/admin/xera/pilot", tags=["xera-admin-pilot"])

Lets an admin / admin-agent link THEIR OWN BNB and TON wallets and try a real
on-chain claim before on-chain claiming is opened to users. It mirrors the user
routes in routes_chain.py and calls exactly the same functions (wallet_link,
claims), so what is tested here is the code users will run.

Security model
  * Every route needs a valid admin token AND a live, active admin_agents row
    (require_active_admin, checked on every call, so revoking access is immediate).
  * The acting identity is the admin's own user id from that token. Nothing in
    a request body or query string can name another user.
  * A user (XERA) token is not an admin token and is rejected.
  * Claim signing (sign-amount / retry) additionally needs XERA_ADMIN_ONCHAIN_PILOT=true.
    The flag only affects these routes; user claim routes are unchanged and stay
    governed by xera_chain_config.onchain_enabled. The distributor address must
    still be configured for the chain.
  * Link / unlink / claim / retry / confirm are written to xera_admin_actions.
    Signatures, proofs and nonces are never logged.
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request

from main import supabase, limiter
from xera.admin_auth import AdminTokenInvalid, require_active_admin
from xera.chain.wallet_link import (
    start_link, verify_and_link, get_linked_wallets, get_wallets, set_manual_wallet, remove_wallet, WalletLinkError,
)
from xera.chain.claims import sign_amount_claim, get_claim_overview, confirm_claim, retry_claim, ClaimError
from xera.chain.config import (
    get_chain_config, bnb_network_public, ChainConfigError, admin_pilot_enabled, admin_pilot_mode,
)
from xera.chain.onchain_indexer import get_vesting_status, IndexerError
from xera.chain import relayer
from pydantic import BaseModel, Field
from xera.routes_chain import (
    _WALLET_ERROR_HTTP, _CLAIM_ERROR_HTTP,
    WalletLinkNonceRequest, WalletLinkVerifyRequest, ManualWalletRequest,
    ClaimAmountRequest, ClaimConfirmRequest, ClaimRetryRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)

_PILOT_OFF = "The admin on-chain pilot is switched off on this server."


def _admin_id(authorization: str) -> int:
    try:
        return require_active_admin(supabase, authorization)
    except AdminTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access has been revoked.")


def _audit(admin_id: int, action: str, details: dict) -> None:
    """Best effort: an audit failure must not mask the real outcome. Never pass secrets here."""
    try:
        supabase.table("xera_admin_actions").insert({
            "admin_id": admin_id, "action": action,
            "old_value": None, "new_value": details, "reason": "admin on-chain pilot",
        }).execute()
    except Exception as exc:
        logger.error("XERA ADMIN PILOT AUDIT FAILED (%s): %s", action, exc)


def _require_pilot() -> None:
    if not admin_pilot_enabled():
        raise HTTPException(status_code=403, detail=_PILOT_OFF)


# ------------------------------------------------------------ status / config

@router.get("/status")
@limiter.limit("30/minute")
def pilot_status(request: Request, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    chains = {}
    for chain in ("BNB", "TON"):
        try:
            cfg = get_chain_config(chain)
            chains[chain] = {
                "distributor_configured": bool(cfg.get("xera_distributor_address")),
                "user_claims_open": bool(cfg.get("onchain_enabled")),
            }
        except ChainConfigError:
            chains[chain] = {"distributor_configured": False, "user_claims_open": False}
    try:
        relayer_addr = relayer.relayer_address()
    except Exception:
        relayer_addr = None
    return {"status": "ok", "admin_id": admin_id, "pilot_enabled": admin_pilot_enabled(), "chains": chains,
            "relayer": {"configured": bool(relayer_addr), "address": relayer_addr}}


@router.get("/chain/config")
@limiter.limit("60/minute")
def pilot_chain_config(request: Request, authorization: str = Header(default="")):
    _admin_id(authorization)
    try:
        return {"status": "ok", "bnb": bnb_network_public()}
    except ChainConfigError:
        raise HTTPException(status_code=503, detail="Chain configuration is temporarily unavailable.")


# ------------------------------------------------------------ wallet linking

@router.post("/wallet/link/nonce")
@limiter.limit("10/minute")
def pilot_link_nonce(request: Request, data: WalletLinkNonceRequest, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    try:
        result = start_link(admin_id, data.chain, data.address)
    except WalletLinkError as e:
        status, message = _WALLET_ERROR_HTTP.get(str(e), (400, "Could not start wallet link."))
        raise HTTPException(status_code=status, detail=message)
    return {"status": "ok", **result}


@router.post("/wallet/link/verify")
@limiter.limit("10/minute")
def pilot_link_verify(request: Request, data: WalletLinkVerifyRequest, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    proof = data.model_dump(exclude={"chain", "address", "nonce"})
    try:
        result = verify_and_link(admin_id, data.chain, data.address, data.nonce, **proof)
    except WalletLinkError as e:
        status, message = _WALLET_ERROR_HTTP.get(str(e), (400, "Could not verify wallet."))
        raise HTTPException(status_code=status, detail=message)
    _audit(admin_id, "ADMIN_PILOT_WALLET_LINKED", {"chain": data.chain.upper(), "address": data.address})
    return {"status": "ok", "wallet": result}


@router.get("/wallet/linked")
@limiter.limit("30/minute")
def pilot_wallet_linked(request: Request, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    return {"status": "ok", "wallets": get_wallets(admin_id)}


@router.post("/wallet/manual")
@limiter.limit("10/minute")
def pilot_wallet_manual(request: Request, data: ManualWalletRequest, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    try:
        wallet = set_manual_wallet(admin_id, data.chain, data.address)
    except WalletLinkError as e:
        status, message = _WALLET_ERROR_HTTP.get(str(e), (400, "Could not save this wallet address."))
        raise HTTPException(status_code=status, detail=message)
    return {"status": "ok", "wallet": wallet,
            "notice": "Wallet address added. This address has not been cryptographically verified as wallet ownership."}


@router.delete("/wallet/{chain}")
@limiter.limit("10/minute")
def pilot_wallet_remove(request: Request, chain: str, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    if chain.upper() not in ("BNB", "TON"):
        raise HTTPException(status_code=400, detail="Unsupported chain.")
    try:
        remove_wallet(admin_id, chain)
    except WalletLinkError as e:
        status, message = _WALLET_ERROR_HTTP.get(str(e), (400, "Could not remove this wallet."))
        raise HTTPException(status_code=status, detail=message)
    _audit(admin_id, "ADMIN_PILOT_WALLET_REMOVED", {"chain": chain.upper()})
    return {"status": "ok"}


# ------------------------------------------------------------ claims

@router.get("/claim/overview")
@limiter.limit("30/minute")
def pilot_claim_overview(request: Request, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    return {"status": "ok", **get_claim_overview(admin_id)}


@router.post("/claim/sign-amount")
@limiter.limit("10/minute")
def pilot_claim_sign_amount(request: Request, data: ClaimAmountRequest, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    _require_pilot()
    try:
        with admin_pilot_mode():
            result = sign_amount_claim(admin_id, data.chain, data.amount)
    except ClaimError as e:
        status, message = _CLAIM_ERROR_HTTP.get(str(e), (400, "Could not sign claim."))
        raise HTTPException(status_code=status, detail=message.replace("{chain}", data.chain.upper()))
    _audit(admin_id, "ADMIN_PILOT_CLAIM_SIGNED", {
        "chain": data.chain.upper(), "amount": data.amount, "reference_id": (result or {}).get("reference_id"),
    })
    return {"status": "ok", "claim": result}


@router.post("/claim/confirm")
@limiter.limit("10/minute")
def pilot_claim_confirm(request: Request, data: ClaimConfirmRequest, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    try:
        with admin_pilot_mode():
            result = confirm_claim(admin_id, data.reference_id, data.transaction_hash)
    except ClaimError as e:
        status, message = _CLAIM_ERROR_HTTP.get(str(e), (400, "Could not confirm claim."))
        raise HTTPException(status_code=status, detail=message)
    _audit(admin_id, "ADMIN_PILOT_CLAIM_CONFIRMED", {
        "reference_id": data.reference_id, "transaction_hash": data.transaction_hash})
    return {"status": "ok", "claim": result}


@router.post("/claim/retry")
@limiter.limit("5/minute")
def pilot_claim_retry(request: Request, data: ClaimRetryRequest, authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    _require_pilot()
    try:
        with admin_pilot_mode():
            result = retry_claim(admin_id, data.reference_id, data.chain)
    except ClaimError as e:
        status, message = _CLAIM_ERROR_HTTP.get(str(e), (400, "Could not retry claim."))
        raise HTTPException(status_code=status, detail=message.replace("{chain}", data.chain.upper()))
    _audit(admin_id, "ADMIN_PILOT_CLAIM_RETRIED", {"chain": data.chain.upper(), "reference_id": data.reference_id})
    return {"status": "ok", "claim": result}


_RELAY_ERROR_HTTP = {
    "relayer_not_configured": (503, "Automatic sending is not set up yet: the relayer gas wallet key is missing on the server."),
    "relayer_unfunded":       (503, "The relayer wallet has no gas. Send it a little tBNB, then try again."),
    "claim_would_revert":     (409, "The contract would reject this claim, so nothing was sent. Check that the distributor holds XERA and has its vesting role."),
    "gas_price_too_high":     (503, "Network gas is above the relayer limit right now. Try again shortly."),
    "wrong_network":          (503, "The server's BNB network does not match this claim."),
    "bnb_rpc_not_configured": (503, "Blockchain access is not configured on the server."),
    "relay_failed":           (502, "Could not send the transaction. Your balance is held; use Try again."),
    "unsupported_chain":      (400, "Automatic sending supports BNB Smart Chain only for now."),
}


class RelayRequest(BaseModel):
    chain: str = Field(..., pattern="^(BNB|bnb)$")
    amount: str | None = Field(default=None, min_length=1, max_length=32)       # new claim
    reference_id: str | None = Field(default=None, min_length=1, max_length=128)  # retry of a held claim


@router.post("/claim/relay")
@limiter.limit("5/minute")
def pilot_claim_relay(request: Request, data: RelayRequest, authorization: str = Header(default="")):
    """
    Reserve + sign a claim for the signed-in admin's own verified wallet, then submit it
    from the relayer gas wallet and confirm it. The admin needs no wallet browser.
    Either `amount` (new claim) or `reference_id` (retry of a failed/expired one).
    """
    admin_id = _admin_id(authorization)
    _require_pilot()
    if bool(data.amount) == bool(data.reference_id):
        raise HTTPException(status_code=400, detail="Send either an amount or a reference_id.")
    try:
        relayer.relayer_address()            # fail BEFORE reserving anything if there is no gas wallet
    except relayer.RelayerError as e:
        status, message = _RELAY_ERROR_HTTP.get(str(e), (503, "Automatic sending is unavailable."))
        raise HTTPException(status_code=status, detail=message)

    if data.reference_id:
        # A claim left SIGNED by an earlier failed relay was never sent by the relayer: release it so it can be retried.
        try:
            row = supabase.table("xera_onchain_claims").select("user_id,status,transaction_hash").eq(
                "reference_id", data.reference_id).limit(1).execute().data
            if row and row[0]["user_id"] == admin_id and row[0]["status"] == "SIGNED" and not row[0].get("transaction_hash"):
                supabase.rpc("xera_mark_onchain_claim_failed", {"p_reference_id": data.reference_id}).execute()
        except Exception:
            pass
    try:
        with admin_pilot_mode():
            claim = (retry_claim(admin_id, data.reference_id, data.chain) if data.reference_id
                     else sign_amount_claim(admin_id, data.chain, data.amount))
    except ClaimError as e:
        status, message = _CLAIM_ERROR_HTTP.get(str(e), (400, "Could not sign claim."))
        raise HTTPException(status_code=status, detail=message.replace("{chain}", data.chain.upper()))

    ref = claim.get("reference_id") or data.reference_id
    claim = {**claim, "reference_id": ref}
    try:
        tx_hash = relayer.submit_bnb_claim(claim)
    except relayer.RelayerError as e:
        try:   # nothing was sent: release the reservation so "Try again" works immediately
            supabase.rpc("xera_mark_onchain_claim_failed", {"p_reference_id": ref}).execute()
        except Exception:
            pass
        status, message = _RELAY_ERROR_HTTP.get(str(e), (502, "Could not send the transaction."))
        _audit(admin_id, "ADMIN_PILOT_CLAIM_RELAY_FAILED", {"reference_id": ref, "reason": str(e)})
        raise HTTPException(status_code=status, detail=message)

    _audit(admin_id, "ADMIN_PILOT_CLAIM_RELAYED", {"reference_id": ref, "transaction_hash": tx_hash, "chain": "BNB"})
    confirmed = None
    if relayer.wait_for_receipt(tx_hash):
        try:
            with admin_pilot_mode():
                confirmed = confirm_claim(admin_id, ref, tx_hash)
            _audit(admin_id, "ADMIN_PILOT_CLAIM_CONFIRMED", {"reference_id": ref, "transaction_hash": tx_hash})
        except ClaimError:
            confirmed = None                 # the page offers "Confirm settlement" with this hash
    return {"status": "ok", "reference_id": ref, "transaction_hash": tx_hash,
            "confirmed": bool(confirmed), "claim": confirmed}


@router.get("/onchain/status")
@limiter.limit("30/minute")
def pilot_onchain_status(request: Request, chain: str = "BNB", authorization: str = Header(default="")):
    admin_id = _admin_id(authorization)
    chain = chain.upper()
    wallet = next((w for w in get_linked_wallets(admin_id) if w["chain"] == chain), None)
    vesting = None
    if wallet:
        try:
            cfg = get_chain_config(chain)
            if cfg.get("xera_vesting_address"):
                vesting = get_vesting_status(vesting_address=cfg["xera_vesting_address"], user_address=wallet["address"])
        except (ChainConfigError, IndexerError):
            vesting = None
    return {"status": "ok", "chain": chain, "linked_wallet": wallet, "vesting": vesting}
