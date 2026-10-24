"""
First-transfer readiness: KYC status, the one-time processing fee, and the
persistent notifications that report on them.

Rules this module enforces (they are the security boundary, not the UI):
  * KYC is VERIFIED only when an authorised backend action says so
    (review_kyc by an active admin, or a future provider callback). Nothing a
    browser sends can set it. submit_kyc can only move a user to PENDING.
  * The fee is PAID only when a server-verified payment says so. There is no
    function in this module that marks a fee paid from a request, and the
    paid row must match the configured amount AND currency to count.
  * transfer_missing()/require_transfer_ready() are called by the claim code
    itself (xera.chain.claims / migration), so an API request cannot skip them.
  * The admin on-chain pilot is exempt only while it is actually active
    (XERA_ADMIN_ONCHAIN_PILOT=true AND inside admin_pilot_mode()). Switch the
    env var to false and admins are gated like everyone else.
  * If the tables can't be read, the gate FAILS CLOSED (requirements missing).
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from main import supabase
from xera.chain.config import admin_pilot_active

logger = logging.getLogger(__name__)

KYC_STATUSES = ("UNVERIFIED", "PENDING", "VERIFIED", "FAILED", "INFO_REQUIRED")
FEE_STATUSES = ("UNPAID", "PENDING", "PAID", "FAILED")

REQ_KYC = "kyc_not_verified"
REQ_FEE = "fee_not_paid"


class TransferRequirementsError(Exception):
    """First-transfer requirements are incomplete. `.missing` lists which."""

    def __init__(self, missing: list):
        super().__init__("transfer_requirements_incomplete")
        self.missing = list(missing)


class KycError(Exception):
    """Short machine-readable code; the route maps it to an HTTP response."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------ fee config

def fee_config() -> dict:
    """The fee the product intends to charge. Currency/amount are config, never hard-coded in checks."""
    try:
        amount_minor = int(os.getenv("XERA_TRANSFER_FEE_AMOUNT_MINOR", "100"))
    except ValueError:
        amount_minor = 100
    return {
        "amount_minor": amount_minor,
        "currency": (os.getenv("XERA_TRANSFER_FEE_CURRENCY", "USD") or "USD").strip().upper(),
        # Off until payment config, webhook verification, disclosures and refund policy are ready.
        "collection_enabled": os.getenv("XERA_FEE_COLLECTION_ENABLED", "false").strip().lower() in ("1", "true", "yes"),
    }


# ------------------------------------------------------------ reads

def _first(res):
    data = getattr(res, "data", None)
    if isinstance(data, list):
        return data[0] if data else None
    return data or None


def get_kyc(user_id: int) -> dict:
    """Server-confirmed KYC state. No row = UNVERIFIED. Unreadable = UNVERIFIED + unavailable."""
    try:
        row = _first(supabase.table("xera_kyc").select("*").eq("user_id", user_id).limit(1).execute())
    except Exception as exc:
        logger.warning("xera_kyc read failed: %s", exc)
        return {"status": "UNVERIFIED", "note": None, "submitted_at": None, "unavailable": True}
    if not row:
        return {"status": "UNVERIFIED", "note": None, "submitted_at": None, "unavailable": False}
    status = row.get("status") if row.get("status") in KYC_STATUSES else "UNVERIFIED"
    return {
        "status": status,
        "note": row.get("review_note") if status in ("FAILED", "INFO_REQUIRED") else None,
        "submitted_at": row.get("submitted_at"),
        "unavailable": False,
    }


def _fee_row_counts_as_paid(row: dict, cfg: dict) -> bool:
    return (
        row.get("status") == "PAID"
        and bool(row.get("payment_reference"))
        and row.get("amount_minor") == cfg["amount_minor"]
        and (row.get("currency") or "").upper() == cfg["currency"]
    )


def get_fee(user_id: int) -> dict:
    cfg = fee_config()
    base = {"amount_minor": cfg["amount_minor"], "currency": cfg["currency"],
            "collection_enabled": cfg["collection_enabled"]}
    try:
        row = _first(supabase.table("xera_transfer_fee").select("*").eq("user_id", user_id).limit(1).execute())
    except Exception as exc:
        logger.warning("xera_transfer_fee read failed: %s", exc)
        return {**base, "status": "UNPAID", "unavailable": True}
    if not row:
        return {**base, "status": "UNPAID", "unavailable": False}
    if row.get("status") == "PAID" and not _fee_row_counts_as_paid(row, cfg):
        # A PAID row that doesn't match the configured amount/currency is never treated as paid.
        logger.error("xera_transfer_fee row for user %s is PAID but amount/currency/reference don't match config", user_id)
        return {**base, "status": "UNPAID", "unavailable": False}
    status = row.get("status") if row.get("status") in FEE_STATUSES else "UNPAID"
    return {**base, "status": status, "unavailable": False}


def list_notifications(user_id: int, limit: int = 20) -> list:
    try:
        res = (supabase.table("xera_notifications").select("*").eq("user_id", user_id)
               .order("created_at", desc=True).limit(limit).execute())
        rows = res.data or []
    except Exception as exc:
        logger.warning("xera_notifications read failed: %s", exc)
        return []
    return [{"id": r.get("id"), "kind": r.get("kind"), "title": r.get("title"),
             "body": r.get("body"), "created_at": r.get("created_at"), "read": bool(r.get("read_at"))}
            for r in rows]


# ------------------------------------------------------------ gate

def transfer_missing(user_id: int) -> list:
    """Which first-transfer requirements (KYC / fee) are NOT satisfied. [] = ready."""
    if admin_pilot_active():
        return []
    missing = []
    if get_kyc(user_id)["status"] != "VERIFIED":
        missing.append(REQ_KYC)
    if get_fee(user_id)["status"] != "PAID":
        missing.append(REQ_FEE)
    return missing


def require_transfer_ready(user_id: int) -> None:
    missing = transfer_missing(user_id)
    if missing:
        raise TransferRequirementsError(missing)


def readiness_summary(user_id: int) -> dict:
    """Everything the dashboard cards need, all server-confirmed."""
    return {
        "kyc": get_kyc(user_id),
        "fee": get_fee(user_id),
        "missing": transfer_missing(user_id),
        "notifications": list_notifications(user_id),
    }


# ------------------------------------------------------------ notifications

def notify(user_id: int, kind: str, title: str, body: str = "", dedupe_key: str | None = None) -> None:
    """Best effort: a notification failure never blocks the action it reports."""
    try:
        if dedupe_key:
            existing = (supabase.table("xera_notifications").select("id")
                        .eq("user_id", user_id).eq("dedupe_key", dedupe_key).limit(1).execute())
            if existing.data:
                return
        supabase.table("xera_notifications").insert({
            "user_id": user_id, "kind": kind, "title": title, "body": body, "dedupe_key": dedupe_key,
        }).execute()
    except Exception as exc:
        logger.warning("xera notification write failed: %s", exc)


# ------------------------------------------------------------ fee payment

FEE_REF_PREFIX = "xera-fee-"


class ReadinessError(Exception):
    """Short machine-readable code from the fee webhook paths; routes map it to HTTP."""


class FeePaymentError(Exception):
    """Short machine-readable code for starting a fee payment; the route maps it to HTTP."""


def new_fee_reference(user_id: int) -> str:
    # The user id is only a routing hint. A fee is never credited until NOWPayments/Paystack
    # itself confirms a payment with this exact order id, and only we can create those.
    return f"{FEE_REF_PREFIX}{int(user_id)}-{uuid.uuid4().hex}"


def is_fee_reference(reference) -> bool:
    return isinstance(reference, str) and reference.startswith(FEE_REF_PREFIX)


def _fee_reference_user_id(reference: str):
    try:
        return int(reference[len(FEE_REF_PREFIX):].split("-", 1)[0])
    except (ValueError, IndexError):
        return None


def _write_fee_row(user_id: int, patch: dict) -> None:
    patch = {**patch, "updated_at": _now()}
    existing = supabase.table("xera_transfer_fee").select("user_id").eq("user_id", user_id).limit(1).execute()
    if existing.data:
        supabase.table("xera_transfer_fee").update(patch).eq("user_id", user_id).execute()
    else:
        supabase.table("xera_transfer_fee").insert({"user_id": user_id, **patch}).execute()


def start_fee_payment(user_id: int) -> dict:
    """Create a USDT (BEP-20) invoice for the one-time fee. Returns where to send the customer."""
    from xera.payments.base import PaymentProviderError
    from xera.payments.crypto_provider import CryptoHashrateProvider, crypto_payments_enabled
    from xera.payments.nowpayments_provider import CHARGE_CURRENCY

    cfg = fee_config()
    if not cfg["collection_enabled"]:
        raise FeePaymentError("fee_collection_not_enabled")
    if cfg["currency"] != CHARGE_CURRENCY:
        raise FeePaymentError("fee_currency_unsupported")   # crypto invoices are priced in USD
    if not crypto_payments_enabled():
        raise FeePaymentError("crypto_payments_not_yet_configured")
    current = get_fee(user_id)
    if current.get("unavailable"):
        raise FeePaymentError("fee_unavailable")
    if current["status"] == "PAID":
        raise FeePaymentError("fee_already_paid")

    reference = new_fee_reference(user_id)
    try:
        init = CryptoHashrateProvider().initialize(
            reference=reference, amount=cfg["amount_minor"] / 100, currency=CHARGE_CURRENCY,
            user_id=user_id, metadata={"product": "xera_transfer_fee"},
        )
    except PaymentProviderError as exc:
        logger.error("XERA fee payment init failed for user %s: %s", user_id, exc)
        raise FeePaymentError("fee_provider_unavailable")

    try:
        _write_fee_row(user_id, {"status": "PENDING", "provider": "CRYPTO"})
    except Exception as exc:   # cosmetic status only; the payment itself does not depend on it
        logger.warning("xera_transfer_fee PENDING write failed: %s", exc)
    return {"invoice_url": init["invoice_url"], "reference": reference,
            "amount_minor": cfg["amount_minor"], "currency": cfg["currency"], "asset": init["asset"]}


def _mark_fee_paid(user_id: int, reference: str, provider_name: str, amount_minor: int, currency: str) -> dict:
    existing = _first(supabase.table("xera_transfer_fee").select("*").eq("user_id", user_id).limit(1).execute())
    if existing and existing.get("status") == "PAID":
        if existing.get("payment_reference") == reference:
            return {"handled": True, "already_paid": True}       # webhook retry
        logger.critical("XERA fee: user %s paid the fee a SECOND time (ref=%s) — refund required", user_id, reference)
        return {"handled": True, "needs_refund": True}
    _write_fee_row(user_id, {
        "status": "PAID", "amount_minor": amount_minor, "currency": currency, "provider": provider_name,
        "payment_reference": reference, "paid_at": _now(),
    })
    notify(user_id, "fee_paid", "Processing fee received", "Your one-time processing fee is confirmed.",
           dedupe_key=f"fee_paid:{reference}")
    return {"handled": True, "paid": True}


def _check_fee_amount(verified: dict, reference: str) -> None:
    cfg = fee_config()
    if verified.get("amount_minor") != cfg["amount_minor"] or (verified.get("currency") or "").upper() != cfg["currency"]:
        logger.critical("XERA fee: confirmed payment amount/currency does not match config (ref=%s, got %s %s) — manual review",
                        reference, verified.get("amount_minor"), verified.get("currency"))
        raise ReadinessError("fee_amount_mismatch")


def handle_fee_ipn(payload: dict) -> dict:
    """NOWPayments IPN for a fee invoice. The caller has ALREADY verified the IPN signature."""
    from xera.payments import nowpayments_provider as np
    from xera.payments.crypto_provider import CryptoHashrateProvider

    reference = payload.get("order_id") or ""
    user_id = _fee_reference_user_id(reference) if is_fee_reference(reference) else None
    if user_id is None:
        return {"handled": False}
    status = str(payload.get("payment_status", "")).lower()

    if status == np.PAID_STATUS:
        verified = CryptoHashrateProvider().verify(reference=reference, payment_id=payload.get("payment_id"))
        if not verified["confirmed"]:
            raise ReadinessError("payment_verification_failed")
        _check_fee_amount(verified, reference)
        return _mark_fee_paid(user_id, reference, "CRYPTO", verified["amount_minor"], verified["currency"])

    if status in np.FAILED_STATUSES or status == np.EXPIRED_STATUS:
        row = _first(supabase.table("xera_transfer_fee").select("*").eq("user_id", user_id).limit(1).execute())
        if row and row.get("status") == "PENDING":
            _write_fee_row(user_id, {"status": "FAILED"})
        return {"handled": True}
    return {"handled": False}


def handle_fee_webhook(raw_body: bytes, signature_header: str, payload: dict) -> dict:
    """Paystack webhook for a fee reference (the Paystack route hands these over)."""
    from xera.payments.paystack_provider import PaystackHashrateProvider, verify_webhook_signature
    if not verify_webhook_signature(raw_body, signature_header):
        raise ReadinessError("invalid_webhook_signature")
    data = payload.get("data") or {}
    reference = data.get("reference", "")
    user_id = _fee_reference_user_id(reference) if is_fee_reference(reference) else None
    if user_id is None or payload.get("event") != "charge.success":
        return {"handled": False}
    verified = PaystackHashrateProvider().verify(reference=reference)
    if not verified["confirmed"]:
        raise ReadinessError("payment_verification_failed")
    _check_fee_amount(verified, reference)
    return _mark_fee_paid(user_id, reference, "PAYSTACK", verified["amount_minor"], verified["currency"])


# ------------------------------------------------------------ KYC workflow (manual review)

_ID_TYPES = ("national_id", "passport", "drivers_license", "voters_id", "other")


def submit_kyc(user_id: int, legal_name: str, country: str, id_type: str, id_number: str) -> dict:
    """
    User submits details for review. This can ONLY result in PENDING. Only the last 4
    characters of the ID number are kept; the full number is never stored or logged.
    """
    legal_name = " ".join((legal_name or "").split())
    country = (country or "").strip().upper()
    id_type = (id_type or "").strip().lower()
    compact = "".join(ch for ch in (id_number or "") if ch.isalnum())
    if len(legal_name) < 3 or len(legal_name) > 120:
        raise KycError("invalid_name")
    if len(country) < 2 or len(country) > 56:
        raise KycError("invalid_country")
    if id_type not in _ID_TYPES:
        raise KycError("invalid_id_type")
    if len(compact) < 4:
        raise KycError("invalid_id_number")
    last4 = compact[-4:]  # taken from the FULL cleaned number, not a truncated copy

    current = get_kyc(user_id)
    if current.get("unavailable"):
        raise KycError("kyc_unavailable")
    if current["status"] in ("VERIFIED", "PENDING"):
        raise KycError("kyc_already_" + current["status"].lower())

    row = {
        "user_id": user_id, "status": "PENDING", "method": "MANUAL",
        "legal_name": legal_name, "country": country, "id_type": id_type, "id_last4": last4,
        "submitted_at": _now(), "reviewed_at": None, "reviewed_by": None, "review_note": None,
        "updated_at": _now(),
    }
    existing = supabase.table("xera_kyc").select("user_id").eq("user_id", user_id).limit(1).execute()
    if existing.data:
        supabase.table("xera_kyc").update(row).eq("user_id", user_id).execute()
    else:
        supabase.table("xera_kyc").insert(row).execute()
    return {"status": "PENDING"}


_REVIEW_NOTIFY = {
    "VERIFIED": ("kyc_verified", "Identity verified", "Your identity has been verified."),
    "FAILED": ("kyc_failed", "Verification unsuccessful", "We couldn't verify your identity."),
    "INFO_REQUIRED": ("kyc_info_required", "More information needed", "We need more information to verify your identity."),
}


def review_kyc(admin_id: int, user_id: int, decision: str, note: str = "") -> dict:
    """Authorised admin decision. The route has already confirmed admin_id is an ACTIVE admin."""
    decision = (decision or "").upper()
    if decision not in _REVIEW_NOTIFY:
        raise KycError("invalid_decision")
    if admin_id == user_id:
        raise KycError("cannot_review_own_kyc")
    row = _first(supabase.table("xera_kyc").select("*").eq("user_id", user_id).limit(1).execute())
    if not row:
        raise KycError("kyc_not_found")
    if row.get("status") != "PENDING":
        raise KycError("kyc_not_pending")
    note = (note or "").strip()[:500]
    if decision in ("FAILED", "INFO_REQUIRED") and not note:
        raise KycError("note_required")

    supabase.table("xera_kyc").update({
        "status": decision, "reviewed_by": admin_id, "reviewed_at": _now(),
        "review_note": note or None, "updated_at": _now(),
    }).eq("user_id", user_id).execute()

    kind, title, body = _REVIEW_NOTIFY[decision]
    notify(user_id, kind, title, (note or body), dedupe_key=f"{kind}:{row.get('submitted_at')}")
    return {"user_id": user_id, "status": decision}


def list_kyc(status: str = "PENDING", limit: int = 100) -> list:
    """Review queue by status. MORE_INFO is accepted as an alias of INFO_REQUIRED."""
    status = (status or "PENDING").upper()
    if status == "MORE_INFO":
        status = "INFO_REQUIRED"
    if status not in KYC_STATUSES:
        raise KycError("invalid_status")
    res = (supabase.table("xera_kyc")
           .select("user_id,status,legal_name,country,id_type,id_last4,submitted_at,reviewed_at,reviewed_by,review_note")
           .eq("status", status).order("submitted_at").limit(limit).execute())
    return res.data or []


def list_pending_kyc(limit: int = 50) -> list:
    return list_kyc("PENDING", limit)


# ------------------------------------------------------------ HTTP shape

_MISSING_TEXT = {
    REQ_KYC: "Identity verification is required before your first transfer.",
    REQ_FEE: "The one-time first-transfer processing fee is required before your first transfer.",
}


def requirements_response(missing: list):
    """403 body the dashboard turns into the 'complete these steps' modal. Never a 200."""
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=403, content={
        "detail": "Complete the required steps before your first transfer.",
        "code": "transfer_requirements_incomplete",
        "missing": list(missing),
        "messages": [_MISSING_TEXT.get(m, m) for m in missing],
    })
