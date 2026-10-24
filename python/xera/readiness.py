"""
XERA first-transfer readiness: KYC status + the one-time processing fee.

What this module is (and is not)
  * The ONLY place that decides whether a user may make their first on-chain
    transfer as far as KYC and the one-time fee are concerned. The claim code
    (xera/chain/claims.py, xera/chain/migration.py) calls
    require_first_transfer_ready() at the backend boundary, so an API request
    cannot skip it by avoiding the frontend.
  * It never touches mining, balances, rewards, the 25/75 split or entitlements.
  * Wallet ownership proof and all other claim checks stay exactly where they
    were (xera/chain/claims.py). Passing this gate does NOT satisfy them.

KYC
  Status is written only by the backend: a user can submit details (-> PENDING),
  and only an authorised admin agent (routes_admin_kyc.py) or a future trusted
  provider callback can move it to VERIFIED / FAILED / MORE_INFO. There is no
  endpoint that accepts a status from the browser. No identity-document images
  are stored; only the minimum needed for a manual review.

Fee
  Status is derived from xera_fee_payments rows that only the backend writes.
  A row becomes PAID only after the backend re-verifies the transaction with
  Paystack AND the verified amount + currency equal the attempt's (checked again
  inside xera_confirm_fee_payment). The browser's return from checkout is never
  treated as proof. Collection is OFF unless XERA_FEE_COLLECTION_ENABLED=true.

Configuration (all optional; defaults are the safe ones)
  XERA_FIRST_TRANSFER_GATE        default "true"  - set "false" ONLY to switch the gate off
  XERA_FEE_COLLECTION_ENABLED     default "false" - live fee collection stays off until true
  XERA_FEE_REFUND_POLICY          the refund-policy text shown before payment. Collection STAYS OFF
                                  while this is empty, even if the flag above is true.
  XERA_FEE_AMOUNT                 default "1.00"
  XERA_FEE_CURRENCY               default "USD"
  XERA_FEE_CALLBACK_URL           where Paystack sends the customer afterwards (optional)
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

import main as _main
from xera.chain.config import admin_pilot_active

logger = logging.getLogger(__name__)

FEE_REFERENCE_PREFIX = "xera-fee-"
_PENDING_FEE_WINDOW = timedelta(hours=1)
_PAYSTACK_BASE_URL = "https://api.paystack.co"

KYC_STATUSES = ("PENDING", "VERIFIED", "FAILED", "MORE_INFO")
_REVIEW_DECISIONS = ("VERIFIED", "FAILED", "MORE_INFO")


class ReadinessError(Exception):
    """Short machine-readable code; the routes map these to HTTP responses."""


class TransferRequirementsError(Exception):
    """Raised by the gate. `.missing` lists what is still required, e.g. ["kyc", "fee"]."""

    def __init__(self, missing):
        super().__init__("first_transfer_requirements_incomplete")
        self.missing = list(missing)


def _sb():
    # Looked up at call time so tests (and a reloaded `main`) always get the live client.
    return _main.supabase


def _now() -> datetime:
    return datetime.now(timezone.utc)


def gate_enabled() -> bool:
    return os.getenv("XERA_FIRST_TRANSFER_GATE", "true").strip().lower() not in ("0", "false", "no", "off")


def fee_refund_policy() -> str:
    return os.getenv("XERA_FEE_REFUND_POLICY", "").strip()[:600]


def fee_collection_enabled() -> bool:
    """Real money is only collected when explicitly switched on AND a refund policy has been written."""
    on = os.getenv("XERA_FEE_COLLECTION_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    return on and bool(fee_refund_policy())


def fee_amount() -> Decimal:
    try:
        amount = Decimal(os.getenv("XERA_FEE_AMOUNT", "1.00").strip())
    except InvalidOperation:
        raise ReadinessError("fee_not_configured")
    if amount <= 0:
        raise ReadinessError("fee_not_configured")
    return amount.quantize(Decimal("0.01"))


def fee_currency() -> str:
    return (os.getenv("XERA_FEE_CURRENCY", "USD").strip() or "USD").upper()


def fee_amount_minor() -> int:
    return int((fee_amount() * 100).to_integral_value())


# ------------------------------------------------------------
# events / notifications (best effort: never block the real outcome)
# ------------------------------------------------------------
def _event(user_id: int, event: str, *, actor_id=None, detail=None) -> None:
    try:
        _sb().table("xera_readiness_events").insert({
            "user_id": user_id, "actor_id": actor_id, "event": event, "detail": detail or {},
        }).execute()
    except Exception as exc:
        logger.error("XERA readiness audit failed (%s): %s", event, exc)


def notify(user_id: int, kind: str, title: str, body: str) -> None:
    try:
        _sb().table("xera_notifications").insert({
            "user_id": user_id, "kind": kind, "title": title, "body": body,
        }).execute()
    except Exception as exc:
        logger.error("XERA notification write failed (%s): %s", kind, exc)


def list_notifications(user_id: int, limit: int = 20) -> list[dict]:
    res = _sb().table("xera_notifications").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit).execute()
    rows = sorted(res.data or [], key=lambda r: (str(r.get("created_at") or ""), r.get("id") or 0), reverse=True)
    return [{"id": r["id"], "kind": r["kind"], "title": r["title"], "body": r["body"],
             "created_at": r.get("created_at"), "read": bool(r.get("read_at"))} for r in rows[:limit]]


def mark_notifications_read(user_id: int) -> None:
    _sb().table("xera_notifications").update({"read_at": _now().isoformat()}).eq("user_id", user_id).is_("read_at", "null").execute()


# ------------------------------------------------------------
# KYC
# ------------------------------------------------------------
def _clean(value, max_len: int) -> str:
    return " ".join(str(value or "").split())[:max_len]


def kyc_status(user_id: int) -> dict:
    res = _sb().table("xera_kyc").select("*").eq("user_id", user_id).limit(1).execute()
    if not res.data:
        return {"status": "UNVERIFIED", "verified": False, "note": None, "submitted_at": None}
    row = res.data[0]
    status = row["status"]
    note = row.get("review_note") if status in ("FAILED", "MORE_INFO") else None
    return {"status": status, "verified": status == "VERIFIED", "note": note, "submitted_at": row.get("submitted_at")}


def submit_kyc(user_id: int, *, legal_name, country, id_type, id_last4) -> dict:
    """User submits details for MANUAL review. Never sets VERIFIED; refuses if already verified."""
    legal_name = _clean(legal_name, 120)
    country = _clean(country, 60)
    id_type = _clean(id_type, 40)
    id_last4 = _clean(id_last4, 40)[-4:]
    if len(legal_name) < 3 or len(country) < 2 or len(id_type) < 2 or len(id_last4) < 3:
        raise ReadinessError("kyc_details_invalid")

    current = _sb().table("xera_kyc").select("*").eq("user_id", user_id).limit(1).execute()
    now = _now().isoformat()
    fields = {"legal_name": legal_name, "country": country, "id_type": id_type, "id_last4": id_last4,
              "status": "PENDING", "submitted_at": now, "review_note": None,
              "reviewed_by": None, "reviewed_at": None, "updated_at": now}
    if current.data:
        row = current.data[0]
        if row["status"] == "VERIFIED":
            raise ReadinessError("kyc_already_verified")
        if row["status"] == "PENDING":
            raise ReadinessError("kyc_already_pending")
        _sb().table("xera_kyc").update(fields).eq("user_id", user_id).execute()
    else:
        _sb().table("xera_kyc").insert({"user_id": user_id, "provider": "MANUAL", **fields}).execute()
    _event(user_id, "KYC_SUBMITTED", detail={"country": country, "id_type": id_type})
    notify(user_id, "KYC_PENDING", "Verification submitted",
           "Your details were received and are waiting for review. You can keep mining in the meantime.")
    return kyc_status(user_id)


def list_kyc_for_review(status: str = "PENDING", limit: int = 100) -> list[dict]:
    status = status.upper()
    if status not in KYC_STATUSES:
        raise ReadinessError("invalid_status")
    res = _sb().table("xera_kyc").select("*").eq("status", status).limit(limit).execute()
    return [{"user_id": r["user_id"], "status": r["status"], "legal_name": r.get("legal_name"),
             "country": r.get("country"), "id_type": r.get("id_type"), "id_last4": r.get("id_last4"),
             "submitted_at": r.get("submitted_at"), "review_note": r.get("review_note")} for r in (res.data or [])]


def review_kyc(admin_id: int, user_id: int, decision: str, note: str = "") -> dict:
    """Authorised admin agent decision. The ONLY way (besides a future provider callback) to set a status."""
    decision = (decision or "").upper()
    if decision not in _REVIEW_DECISIONS:
        raise ReadinessError("invalid_decision")
    note = _clean(note, 300)
    if decision in ("FAILED", "MORE_INFO") and not note:
        raise ReadinessError("note_required")
    res = _sb().table("xera_kyc").select("*").eq("user_id", user_id).limit(1).execute()
    if not res.data:
        raise ReadinessError("kyc_not_found")
    now = _now().isoformat()
    _sb().table("xera_kyc").update({
        "status": decision, "reviewed_by": admin_id, "reviewed_at": now,
        "review_note": note or None, "updated_at": now,
    }).eq("user_id", user_id).execute()
    _event(user_id, f"KYC_{decision}", actor_id=admin_id)
    messages = {
        "VERIFIED": ("KYC_VERIFIED", "Identity verified", "Your identity has been verified."),
        "FAILED": ("KYC_FAILED", "Verification failed", note or "Your verification could not be completed."),
        "MORE_INFO": ("KYC_MORE_INFO", "More information needed", note or "Please resubmit your verification details."),
    }
    kind, title, body = messages[decision]
    notify(user_id, kind, title, body)
    return kyc_status(user_id)


# ------------------------------------------------------------
# Fee
# ------------------------------------------------------------
def _parse_ts(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def fee_status(user_id: int) -> dict:
    res = _sb().table("xera_fee_payments").select("*").eq("user_id", user_id).execute()
    rows = res.data or []
    if any(r["status"] == "PAID" for r in rows):
        status = "PAID"
    else:
        rows = sorted(rows, key=lambda r: (str(r.get("created_at") or ""), r.get("id") or 0), reverse=True)
        status = "UNPAID"
        if rows:
            latest = rows[0]
            created = _parse_ts(latest.get("created_at"))
            if latest["status"] == "FAILED":
                status = "FAILED"
            elif latest["status"] == "PENDING" and (created is None or _now() - created < _PENDING_FEE_WINDOW):
                status = "PENDING"
    try:
        amount, currency = f"{fee_amount():.2f}", fee_currency()
    except ReadinessError:
        amount, currency = None, None
    return {"status": status, "paid": status == "PAID", "amount": amount, "currency": currency,
            "collection_enabled": fee_collection_enabled(), "refund_policy": fee_refund_policy() or None}


def _user_email(user_id: int):
    res = _sb().table("users").select("email").eq("id", user_id).limit(1).execute()
    return (res.data[0].get("email") if res.data else None) or None


def _paystack_secret() -> str:
    key = os.getenv("XERA_PAYSTACK_SECRET_KEY", "")
    if not key:
        raise ReadinessError("payments_unavailable")
    return key


def start_fee_payment(user_id: int) -> dict:
    """Create a PENDING attempt for the authenticated user and a Paystack checkout. Never marks anything paid."""
    if not fee_collection_enabled():
        raise ReadinessError("fee_collection_disabled")
    if fee_status(user_id)["paid"]:
        raise ReadinessError("fee_already_paid")
    amount_minor, currency = fee_amount_minor(), fee_currency()
    email = _user_email(user_id)
    if not email:
        raise ReadinessError("customer_email_required")
    secret = _paystack_secret()

    import uuid
    reference = f"{FEE_REFERENCE_PREFIX}{uuid.uuid4().hex}"
    _sb().table("xera_fee_payments").insert({
        "user_id": user_id, "reference": reference, "amount_minor": amount_minor,
        "currency": currency, "status": "PENDING", "provider": "PAYSTACK",
    }).execute()

    body = {"reference": reference, "email": email, "amount": amount_minor, "currency": currency,
            "metadata": {"user_id": user_id, "product": "xera_first_transfer_fee"}}
    callback = os.getenv("XERA_FEE_CALLBACK_URL", "").strip()
    if callback:
        body["callback_url"] = callback
    try:
        resp = httpx.post(f"{_PAYSTACK_BASE_URL}/transaction/initialize",
                          headers={"Authorization": f"Bearer {secret}"}, json=body, timeout=15)
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        _fail_attempt(reference)
        raise ReadinessError("payments_unavailable")
    if not data.get("status"):
        # e.g. the Paystack account cannot charge this currency: surface it, never substitute another currency.
        logger.error("XERA fee init refused by Paystack: %s", data.get("message"))
        _fail_attempt(reference)
        raise ReadinessError("payment_init_failed")
    _event(user_id, "FEE_CHECKOUT_STARTED", detail={"reference": reference})
    return {"authorization_url": data["data"]["authorization_url"], "reference": reference}


def _fail_attempt(reference: str) -> None:
    try:
        _sb().rpc("xera_fail_fee_payment", {"p_reference": reference}).execute()
    except Exception as exc:
        logger.error("XERA fee attempt could not be marked failed (%s): %s", reference, exc)


def is_fee_reference(reference) -> bool:
    return isinstance(reference, str) and reference.startswith(FEE_REFERENCE_PREFIX)


def apply_verified_fee_payment(reference: str) -> dict:
    """
    Re-verify `reference` with Paystack, then (and only then) ask the database to mark it paid.
    Safe to call repeatedly (webhook retries, the user's return from checkout): the database
    only ever moves PENDING -> PAID once, and refuses a mismatched amount or currency.
    """
    from xera.payments.paystack_provider import PaystackHashrateProvider
    from xera.payments.base import PaymentProviderError

    existing = _sb().table("xera_fee_payments").select("*").eq("reference", reference).limit(1).execute()
    if not existing.data:
        raise ReadinessError("fee_payment_not_found")
    row = existing.data[0]
    previous_status, owner = row["status"], row["user_id"]
    if previous_status == "PAID":
        return {"status": "PAID", "user_id": owner}

    try:
        verified = PaystackHashrateProvider().verify(reference=reference)
    except (PaymentProviderError, RuntimeError):
        raise ReadinessError("payments_unavailable")
    if not verified.get("confirmed"):
        return {"status": row["status"], "user_id": row["user_id"]}

    try:
        res = _sb().rpc("xera_confirm_fee_payment", {
            "p_reference": reference, "p_amount_minor": verified.get("amount_minor"),
            "p_currency": verified.get("currency"), "p_provider_tx_id": verified.get("tx_hash"),
        }).execute()
    except Exception as exc:
        text = str(exc)
        if "fee_amount_mismatch" in text:
            logger.critical("XERA fee: Paystack amount/currency did not match the attempt. reference=%s", reference)
            raise ReadinessError("fee_amount_mismatch")
        if "uq_xera_fee_one_paid_per_user" in text or "duplicate key" in text:
            logger.critical("XERA fee: user paid twice; refund the extra payment. reference=%s", reference)
            return {"status": "PAID", "user_id": row["user_id"], "needs_refund": True}
        raise
    out = res.data[0] if isinstance(res.data, list) and res.data else (res.data or {})
    if out.get("status") == "PAID" and previous_status != "PAID":
        notify(owner, "FEE_PAID", "Processing fee received",
               "Your one-time processing fee was confirmed. Wallet verification and all other requirements still apply.")
    return {"status": out.get("status", "PENDING"), "user_id": owner}


def handle_fee_webhook(raw_body: bytes, signature_header: str, payload: dict) -> dict:
    from xera.payments.paystack_provider import verify_webhook_signature
    if not verify_webhook_signature(raw_body, signature_header):
        raise ReadinessError("invalid_webhook_signature")
    event = payload.get("event")
    reference = (payload.get("data") or {}).get("reference", "")
    if event == "charge.success":
        return {"handled": True, **apply_verified_fee_payment(reference)}
    if event == "charge.failed":
        _fail_attempt(reference)
        return {"handled": True}
    return {"handled": False}


# ------------------------------------------------------------
# The gate
# ------------------------------------------------------------
def missing_requirements(user_id: int) -> list[str]:
    missing = []
    if not kyc_status(user_id)["verified"]:
        missing.append("kyc")
    if not fee_status(user_id)["paid"]:
        missing.append("fee")
    return missing


def require_first_transfer_ready(user_id: int) -> None:
    """
    Raise TransferRequirementsError unless KYC is verified AND the fee is paid.
    Skipped only for the admin on-chain pilot (an authenticated admin testing their own
    wallet; entered solely by routes_admin_chain.py) or when explicitly switched off.
    """
    if admin_pilot_active() or not gate_enabled():
        return
    missing = missing_requirements(user_id)
    if missing:
        raise TransferRequirementsError(missing)


def readiness_overview(user_id: int) -> dict:
    kyc, fee = kyc_status(user_id), fee_status(user_id)
    return {"kyc": kyc, "fee": fee, "missing": [m for m, ok in (("kyc", kyc["verified"]), ("fee", fee["paid"])) if not ok],
            "gate_enabled": gate_enabled()}
