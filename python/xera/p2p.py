"""
XERA in-app P2P transfers (XERA user -> XERA user) — mounted in main.py as:

    from xera.p2p import router as xera_p2p_router
    app.include_router(xera_p2p_router, prefix="/api/xera/transfer", tags=["xera-p2p"])

Rules:
  * The sender is ALWAYS the user in the session token. Nothing in a request
    body can name the sender.
  * Balance moves only inside the Postgres function xera_p2p_transfer
    (migration 20261116_xera_p2p_v1.sql). This module never writes a balance.
  * A sender who has completed every transfer step (KYC verified + one-time fee
    paid, via readiness.transfer_missing) sends free with the normal daily cap.
    A sender who has NOT may still send, but pays a fee on top (default 50% of the
    amount, set in xera_p2p_config) and has a lower daily cap. The recipient always
    gets the full amount. The fee is not paid to any wallet (look-only vault total).
  * The client IP is recorded with each transfer, with a VPN/proxy note when
    an IP checker is set up (xera/ipcheck.py). The note never blocks a transfer.
  * This module does not touch on-chain claims or external-wallet withdrawal.

Routes (all under /api/xera/transfer):
  GET  /me       my XERA ID, limits, and whether I'm ready to send
  POST /lookup   masked name for an XERA ID (so the sender can confirm)
  POST /send     send XERA (idempotent on request_id)
  GET  /ledger   PUBLIC global ledger of transfers (masked IDs only)
"""

import logging
import re
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from main import supabase, limiter
from xera.config import get_config
from xera import readiness
from xera import ipcheck
from utils.rate_limit import get_client_ip
from xera.routes import _current_user_id, _log_security_event

logger = logging.getLogger(__name__)
router = APIRouter()

_XID_RE = re.compile(r"^XR-[A-Z2-9]{8}$")
_REQ_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# DB error text -> (HTTP status, message shown to the user)
_P2P_ERROR_HTTP = [
    ("transfers_disabled",   (403, "Transfers are not open yet.")),
    ("recipient_not_found",  (404, "No XERA user found with that ID.")),
    ("recipient_not_active", (409, "That account can't receive transfers right now.")),
    ("self_transfer",        (400, "You can't send XERA to yourself.")),
    ("amount_out_of_range",  (400, "Amount is outside the allowed range.")),
    ("daily_limit_exceeded", (409, "You've reached your 24-hour sending limit.")),
    ("insufficient_balance", (409, "Not enough available balance for the amount plus any fee. Tokens held for a pending order can't be sent.")),
    ("wallet_not_active",    (403, "Your wallet is suspended.")),
    ("wallet_not_found",     (404, "Wallet not found.")),
    ("request_id_conflict",  (409, "This request ID was already used. Please try again.")),
    ("invalid_amount",       (400, "Enter a valid amount.")),
    ("user_not_found",       (404, "Account not found.")),
]


def _p2p_config() -> dict:
    res = supabase.table("xera_p2p_config").select("*").eq("id", 1).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=503, detail="Transfers are being set up. Please try again shortly.")
    return res.data[0]


def _mask_name(name: str | None) -> str:
    """'John Mensah' -> 'Jo** Me****'. Enough to recognise, not enough to expose."""
    words = [w for w in (name or "").split() if w]
    if not words:
        return "XERA user"
    out = []
    for w in words[:3]:
        keep = 2 if len(w) > 3 else 1
        out.append(w[:keep] + "*" * min(max(len(w) - keep, 1), 5))
    return " ".join(out)


def _normalise_xera_id(raw: str) -> str:
    xid = (raw or "").strip().upper()
    if not _XID_RE.match(xid):
        raise HTTPException(status_code=400, detail="That doesn't look like a valid XERA ID (example: XR-7K4M9P2Q).")
    return xid


class LookupRequest(BaseModel):
    xera_id: str = Field(min_length=3, max_length=20)


class SendRequest(BaseModel):
    xera_id: str = Field(min_length=3, max_length=20)
    amount: Decimal
    request_id: str

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: Decimal) -> Decimal:
        try:
            if not v.is_finite() or v <= 0 or v.as_tuple().exponent < -4:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValueError("Enter a valid amount (up to 4 decimals).")
        return v

    @field_validator("request_id")
    @classmethod
    def _request_id(cls, v: str) -> str:
        if not _REQ_RE.match(v or ""):
            raise ValueError("Invalid request id.")
        return v


@router.get("/me")
@limiter.limit("30/minute")
def p2p_me(request: Request, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    cfg = get_config()
    pc = _p2p_config()
    try:
        xera_id = supabase.rpc("xera_ensure_xera_id", {"p_user_id": user_id}).execute().data
    except Exception as e:
        logger.error("XERA P2P ensure id failed: %s", e)
        raise HTTPException(status_code=503, detail="Could not load your XERA ID. Please try again.")
    missing = readiness.transfer_missing(user_id)
    complete = not missing
    return {
        "status": "ok",
        "xera_id": xera_id,
        "enabled": bool(cfg["system_enabled"] and cfg["transfer_enabled"]),
        "limits": {
            "min": float(pc["min_amount"]),
            "max": float(pc["max_amount"]),
            # The cap that applies to THIS user right now.
            "daily_total": float(pc["daily_max_total"] if complete else pc["unverified_daily_max"]),
        },
        "complete": complete,
        "fee_percent": 0 if complete else pc["unverified_fee_bps"] / 100,
        "missing": missing,
    }


@router.post("/lookup")
@limiter.limit("20/minute")
def p2p_lookup(request: Request, data: LookupRequest, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)
    xid = _normalise_xera_id(data.xera_id)
    res = supabase.table("users").select("id, full_name").eq("xera_id", xid).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="No XERA user found with that ID.")
    row = res.data[0]
    return {
        "status": "ok",
        "xera_id": xid,
        "name": _mask_name(row.get("full_name")),
        "is_self": row["id"] == user_id,
    }


@router.post("/send")
@limiter.limit("10/minute")
def p2p_send(request: Request, data: SendRequest, authorization: str = Header(default="")):
    user_id = _current_user_id(request, authorization)

    cfg = get_config()
    if not (cfg["system_enabled"] and cfg["transfer_enabled"]):
        raise HTTPException(status_code=403, detail="Transfers are not open yet.")

    # Every transfer step done (identity check + one-time fee) = free; otherwise the
    # database applies the unverified fee and the lower daily cap.
    verified = not readiness.transfer_missing(user_id)

    xid = _normalise_xera_id(data.xera_id)
    ip = get_client_ip(request)
    ip_risk = ipcheck.check_ip(ip)
    try:
        res = supabase.rpc("xera_p2p_transfer", {
            "p_sender_user_id": user_id,
            "p_recipient_xera_id": xid,
            "p_amount": str(data.amount),
            "p_request_id": data.request_id,
            "p_sender_verified": verified,
            "p_ip_address": ip if ip and ip != "unknown" else None,
            "p_ip_risk": ip_risk,
        }).execute()
    except Exception as e:
        msg = str(e)
        for code, (status, message) in _P2P_ERROR_HTTP:
            if code in msg:
                if code in ("daily_limit_exceeded", "request_id_conflict", "insufficient_balance"):
                    _log_security_event(user_id, "P2P_REFUSED", request, {"code": code})
                raise HTTPException(status_code=status, detail=message)
        logger.error("XERA P2P transfer failed unexpectedly: %s", msg)
        raise HTTPException(status_code=500, detail="Transfer failed. Nothing was sent. Please try again.")

    row = res.data[0] if isinstance(res.data, list) and res.data else (res.data or {})
    if ip_risk.get("vpn"):
        _log_security_event(user_id, "P2P_VPN_DETECTED", request, {"transfer_id": row.get("id"), "type": ip_risk.get("type")})
    try:
        balance = supabase.table("xera_wallets").select("cached_balance").eq("user_id", user_id).limit(1).execute().data
        new_balance = balance[0]["cached_balance"] if balance else None
    except Exception:
        new_balance = None  # cosmetic only; the transfer itself succeeded

    return {
        "status": "ok",
        "transfer": {
            "id": row.get("id"),
            "amount": row.get("amount"),
            "fee_amount": row.get("fee_amount", 0),
            "recipient_xera_id": row.get("recipient_xera_id"),
            "created_at": row.get("created_at"),
        },
        "new_balance": new_balance,
    }


@router.get("/ledger")
@limiter.limit("30/minute")
def p2p_public_ledger(request: Request, limit: int = 50, offset: int = 0):
    """Public. Masked IDs, amount and time only: no names, no user ids."""
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    res = (
        supabase.table("xera_p2p_public_ledger")
        .select("id, sender, recipient, amount, status, created_at")
        .order("id", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"status": "ok", "transfers": res.data or []}
