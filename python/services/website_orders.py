"""
Website Creation orders: pricing, payment (Paystack / USDT crypto), receipt, uploads.

Everything that decides money lives here and on the server. The browser only says
"this request, this method, use XERA yes/no"; it is told the result.

Pricing
    Every package is 50% off its list price (cash: Starter 500, Business 1,000, Premium 1,850, WhatsApp bot 500).
    Paying with XERA takes a further 20% off the cash price (Starter 400 ... Premium 1,480) (WEBSITE_XERA_DISCOUNT_PCT).
    The XERA saving reuses the EVOS Data hold -> consume -> release lifecycle
    (services/evosdata/xera_discount.py), keyed by the payment reference. It is a
    promotional saving set by EVOS; it does not give XERA a cash value.

Payment
    * Paystack: GHS, confirmed by the Paystack webhook (or the page's own refresh, which
      asks Paystack directly). Amount and currency are compared with what we stored.
    * Crypto: USDT (BEP-20) through NOWPayments, never XERA itself. The USD charge is stored
      at purchase time (rounded up) and compared with what NOWPayments reports.
    Neither rail trusts a webhook body or a browser "success": both re-read the payment
    from the provider before the order is marked paid, and marking paid is atomic
    (UPDATE ... WHERE payment_status <> 'paid'), so a repeated webhook is harmless.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import httpx
from fastapi.concurrency import run_in_threadpool

from utils.email_sender import send_email
from utils.supabase_admin import (
    count_website_files,
    get_website_request,
    insert_website_file_row,
    patch_website_request,
    upload_website_file,
)
from utils.text_sanitize import clean_text
from xera.payments import nowpayments_provider as nowpayments
from xera.payments.base import PaymentProviderError
from xera.payments.paystack_provider import PaystackHashrateProvider, _secret_key

logger = logging.getLogger(__name__)

REFERENCE_PREFIX = "evos-web-"
CENT = Decimal("0.01")

# list = the "was" price shown struck through; price = what a cash customer pays.
PACKAGES = {
    "starter":  {"label": "Starter website",  "list": Decimal("1000"), "price": Decimal("500")},
    "business": {"label": "Business website", "list": Decimal("2000"), "price": Decimal("1000")},
    "premium":  {"label": "Premium website",  "list": Decimal("3700"), "price": Decimal("1850")},
    # PLACEHOLDER list price: confirm the real WhatsApp bot price (only these two numbers need changing).
    "whatsapp_bot": {"label": "WhatsApp bot", "list": Decimal("1000"), "price": Decimal("500")},
}  # "custom" is quote-only: never payable online.

MAX_FILES = 8
MAX_FILE_BYTES = 5 * 1024 * 1024


class WebsiteOrderError(Exception):
    """`code` is stable; `message` is user-facing; `status` is the HTTP status to use."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def is_website_reference(reference) -> bool:
    return isinstance(reference, str) and reference.startswith(REFERENCE_PREFIX)


def xera_pct() -> Decimal:
    try:
        pct = Decimal(os.getenv("WEBSITE_XERA_DISCOUNT_PCT", "20"))
    except Exception:
        pct = Decimal("20")
    return min(max(pct, Decimal("0")), Decimal("100"))


def _money(v) -> Decimal:
    return Decimal(str(v)).quantize(CENT, ROUND_HALF_UP)


# --------------------------------------------------------------------- pricing

def package_pricing(package: str) -> dict | None:
    """Public price card for one package, or None when it is quote-only."""
    p = PACKAGES.get(package)
    if not p:
        return None
    list_price, price = _money(p["list"]), _money(p["price"])
    off_pct = int(((list_price - price) / list_price * 100).quantize(Decimal("1"), ROUND_HALF_UP)) if list_price > price else 0
    xera_saving = (price * xera_pct() / 100).quantize(CENT, ROUND_HALF_UP)
    return {
        "package": package,
        "label": p["label"],
        "currency": "GHS",
        "list_price": float(list_price),
        "price": float(price),
        "percent_off": off_pct,
        "xera_percent": int(xera_pct()),
        "xera_saving": float(xera_saving),
        "price_with_xera": float(price - xera_saving),
    }


def all_pricing() -> dict:
    return {k: package_pricing(k) for k in PACKAGES}


def paystack_enabled() -> bool:
    return bool(os.getenv("XERA_PAYSTACK_SECRET_KEY", "").strip())


def crypto_enabled() -> bool:
    return nowpayments.configured() and bool(os.getenv("XERA_NOWPAYMENTS_IPN_URL", "").strip())


def methods_available() -> dict:
    return {"paystack": paystack_enabled(), "crypto": crypto_enabled()}


def _return_url() -> str:
    return os.getenv("WEBSITE_PAYMENT_RETURN_URL", "").strip() or "https://evoshub.xyz/website-creation.html"


# ------------------------------------------------------------------- XERA saving

def _xera_cfg(sb) -> dict:
    from services.evosdata import xera_discount
    cfg = xera_discount.load_config(sb)           # global on/off switch, XERA-per-GHS rate, KYC rule
    pct = xera_pct()
    cfg["discount_pct"] = pct
    cfg["max_pct"] = pct                          # website saving is its own percentage
    return cfg


def xera_quote(sb, xera_user_id: int | None, cash_price) -> dict:
    """Public quote for the XERA saving on `cash_price` (never raises for 'not eligible')."""
    from services.evosdata import xera_discount
    q = xera_discount.quote(sb, xera_user_id, float(cash_price), _xera_cfg(sb))
    return q


# ----------------------------------------------------------------------- payment

def _require_payable(row: dict) -> dict:
    pricing = package_pricing(row["package"])
    if not pricing:
        raise WebsiteOrderError("not_payable", "This package is priced by quote. Please chat with our team.")
    if row.get("payment_status") == "paid":
        raise WebsiteOrderError("already_paid", "This order is already paid.", 409)
    return pricing


async def start_payment(row: dict, *, method: str, use_xera: bool, xera_user_id: int | None) -> dict:
    """Create the provider checkout and record the quoted amounts. Returns {url, reference, ...}."""
    if method not in ("paystack", "crypto"):
        raise WebsiteOrderError("bad_method", "Choose Paystack or crypto.")
    if not methods_available()[method]:
        raise WebsiteOrderError("method_unavailable", "That payment method is not available right now.", 503)
    pricing = _require_payable(row)

    from main import supabase as sb
    from services.evosdata import xera_discount

    cash = _money(pricing["price"])
    discount = Decimal("0.00")
    quote = None
    reference = f"{REFERENCE_PREFIX}{uuid.uuid4().hex}"

    # Free any XERA held for an earlier, unpaid attempt before we price this one.
    old_ref = row.get("payment_reference")
    if old_ref and row.get("payment_status") in ("pending", "failed"):
        await run_in_threadpool(xera_discount.release, sb, old_ref)

    if use_xera:
        if not xera_user_id:
            raise WebsiteOrderError("xera_login_required", "Sign in to XERA to use your XERA saving.", 401)
        quote = await run_in_threadpool(xera_quote, sb, xera_user_id, cash)
        if not quote.get("eligible"):
            raise WebsiteOrderError("xera_not_eligible", quote.get("message") or "The XERA saving is not available.", 409)
        discount = _money(quote["_calc"]["discount_ghs"])
        try:
            await run_in_threadpool(xera_discount.place_hold, sb, xera_user_id, reference, quote)
        except xera_discount.DiscountError as de:
            raise WebsiteOrderError(de.code, de.message, 409)

    amount_due = cash - discount
    fields = {
        "list_price_ghs": float(pricing["list_price"]),
        "price_ghs": float(cash),
        "xera_discount_ghs": float(discount),
        "amount_due_ghs": float(amount_due),
        "payment_status": "pending",
        "payment_method": method,
        "payment_reference": reference,
        "crypto_usd_cents": None,
        "contact_path": "pay_now",
    }

    try:
        if method == "paystack":
            url = await run_in_threadpool(_paystack_checkout, reference, row["email"], amount_due, row["id"])
            extra = {}
        else:
            cents, ccy = await run_in_threadpool(nowpayments.to_charge, amount_due, "GHS")
            fields["crypto_usd_cents"] = cents
            res = await run_in_threadpool(
                nowpayments.NowPaymentsProvider().initialize,
                reference=reference, amount=Decimal(cents) / 100, currency=ccy,
                user_id=0, metadata={"product": "website_order", "request_id": row["id"]},
            )
            url = res["invoice_url"]
            extra = {"usd": float(Decimal(cents) / 100), "asset": res.get("asset")}
        await patch_website_request(row["id"], fields)
    except Exception:
        # The customer never reached a checkout: do not keep their XERA held.
        if use_xera:
            await run_in_threadpool(xera_discount.release, sb, reference)
        raise

    return {
        "url": url, "reference": reference, "method": method,
        "amount_due": float(amount_due), "xera_discount": float(discount), **extra,
    }


def _paystack_checkout(reference: str, email: str, amount_due: Decimal, request_id: str) -> str:
    sep = "&" if "?" in _return_url() else "?"
    try:
        resp = httpx.post(
            "https://api.paystack.co/transaction/initialize",
            headers={"Authorization": f"Bearer {_secret_key()}"},
            json={
                "reference": reference,
                "email": email,
                "amount": int((amount_due * 100).to_integral_value(ROUND_HALF_UP)),   # pesewas
                "currency": "GHS",
                "callback_url": f"{_return_url()}{sep}pay=paystack",
                "metadata": {"product": "website_order", "request_id": request_id},
            },
            timeout=15,
        )
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise PaymentProviderError("paystack_unreachable") from e
    url = (data.get("data") or {}).get("authorization_url") if data.get("status") else None
    if not url:
        raise PaymentProviderError(f"paystack_init_failed: {data.get('message')}")
    return url


async def confirm_payment(reference: str, *, amount_minor, currency, provider_ref: str | None = None) -> dict:
    """
    Mark the order paid once the provider has CONFIRMED the payment. Idempotent.
    `amount_minor`/`currency` come from the provider's own API response, never from a webhook body.
    """
    row = await get_website_request(payment_reference=reference)
    if not row:
        logger.critical("WEBSITE ORDER: paid reference %s matches no request (superseded attempt?) - review manually", reference)
        return {"handled": False, "reason": "unknown_reference"}
    if row.get("payment_status") == "paid":
        return {"handled": True, "already_paid": True}

    if row.get("payment_method") == "paystack":
        expected = (int((_money(row["amount_due_ghs"]) * 100).to_integral_value()), "GHS")
    else:
        expected = (row.get("crypto_usd_cents"), "USD")
    if amount_minor != expected[0] or (currency or "").upper() != expected[1]:
        logger.critical(
            "WEBSITE ORDER: amount mismatch for %s: provider says %s %s, expected %s %s - NOT marking paid",
            reference, amount_minor, currency, expected[0], expected[1],
        )
        return {"handled": False, "reason": "amount_mismatch"}

    now = datetime.now(timezone.utc)
    receipt_no = f"EVX-WEB-{now:%Y%m%d}-{row['id'].replace('-', '')[:6].upper()}"
    updated = await patch_website_request(
        row["id"],
        {
            "payment_status": "paid",
            "paid_at": now.isoformat(),
            "receipt_no": receipt_no,
            "status": "in_review" if row.get("status") == "new" else row.get("status", "new"),
        },
        only_if={"payment_status": "neq.paid"},
    )
    if not updated:
        return {"handled": True, "already_paid": True}      # a parallel confirmation won the race

    # The customer has paid: nothing below may undo that.
    if float(row.get("xera_discount_ghs") or 0) > 0:
        try:
            from main import supabase as sb
            from services.evosdata import xera_discount
            await run_in_threadpool(xera_discount.consume, sb, reference)
        except Exception as exc:
            logger.error("WEBSITE ORDER: XERA consume failed for %s: %s", reference, exc)
    try:
        await run_in_threadpool(_send_paid_emails, updated)
    except Exception as exc:
        logger.warning("WEBSITE ORDER: receipt email failed for %s: %s", reference, exc)
    return {"handled": True, "receipt_no": receipt_no}


async def mark_payment_failed(reference: str) -> dict:
    """Provider says failed/expired: free held XERA and let the customer try again."""
    row = await get_website_request(payment_reference=reference)
    if not row:
        return {"handled": False}
    updated = await patch_website_request(row["id"], {"payment_status": "failed"}, only_if={"payment_status": "eq.pending"})
    if updated and float(row.get("xera_discount_ghs") or 0) > 0:
        try:
            from main import supabase as sb
            from services.evosdata import xera_discount
            await run_in_threadpool(xera_discount.release, sb, reference)
        except Exception as exc:
            logger.error("WEBSITE ORDER: XERA release failed for %s: %s", reference, exc)
    return {"handled": bool(updated)}


async def reconcile_paystack(row: dict) -> dict:
    """Page refresh after the Paystack redirect: ask Paystack directly instead of waiting for the webhook."""
    if row.get("payment_status") != "pending" or row.get("payment_method") != "paystack" or not row.get("payment_reference"):
        return row
    try:
        v = await run_in_threadpool(PaystackHashrateProvider().verify, reference=row["payment_reference"])
    except PaymentProviderError:
        return row
    if v.get("confirmed"):
        await confirm_payment(row["payment_reference"], amount_minor=v.get("amount_minor"), currency=v.get("currency"))
        return await get_website_request(request_id=row["id"]) or row
    return row


async def handle_paystack_webhook(payload: dict) -> dict:
    """Signature already checked by the route. Success is re-read from Paystack before it counts."""
    reference = (payload.get("data") or {}).get("reference", "")
    if payload.get("event") != "charge.success":
        return {"handled": False}
    v = await run_in_threadpool(PaystackHashrateProvider().verify, reference=reference)
    if not v.get("confirmed"):
        return {"handled": False, "reason": "not_confirmed"}
    return await confirm_payment(reference, amount_minor=v.get("amount_minor"), currency=v.get("currency"))


async def handle_nowpayments_ipn(payload: dict) -> dict:
    """Signature already checked by the route. A `finished` status triggers a fresh read from NOWPayments."""
    reference = payload.get("order_id") or ""
    status = str(payload.get("payment_status", "")).lower()
    if status == nowpayments.PAID_STATUS:
        v = await run_in_threadpool(
            nowpayments.NowPaymentsProvider().verify, reference=reference, payment_id=payload.get("payment_id"),
        )
        if not v.get("confirmed"):
            return {"handled": False, "reason": "not_confirmed"}
        return await confirm_payment(reference, amount_minor=v.get("amount_minor"), currency=v.get("currency"),
                                     provider_ref=v.get("tx_hash"))
    if status in nowpayments.FAILED_STATUSES or status == nowpayments.EXPIRED_STATUS:
        return await mark_payment_failed(reference)
    return {"handled": True}      # waiting / confirming / sending: nothing to do yet


# ----------------------------------------------------------------------- receipt

_METHOD_LABEL = {"paystack": "Paystack (card / mobile money)", "crypto": "USDT (BEP-20) via NOWPayments"}


def build_receipt(row: dict) -> dict:
    if row.get("payment_status") != "paid" or not row.get("receipt_no"):
        raise WebsiteOrderError("not_paid", "No receipt yet: this order is not paid.", 404)
    pkg = PACKAGES.get(row["package"], {})
    list_price = _money(row.get("list_price_ghs") or 0)
    price = _money(row.get("price_ghs") or 0)
    xera = _money(row.get("xera_discount_ghs") or 0)
    return {
        "receipt_no": row["receipt_no"],
        "paid_at": row.get("paid_at"),
        "customer": {
            "name": row["full_name"], "email": row["email"],
            "phone": row.get("phone"), "business": row.get("business_name"),
        },
        "item": pkg.get("label", row["package"].title()),
        "currency": "GHS",
        "list_price": float(list_price),
        "package_discount": float(max(list_price - price, Decimal("0"))),
        "price": float(price),
        "xera_discount": float(xera),
        "amount_paid": float(_money(row.get("amount_due_ghs") or 0)),
        "crypto_usd": (row.get("crypto_usd_cents") or 0) / 100 if row.get("payment_method") == "crypto" else None,
        "method": _METHOD_LABEL.get(row.get("payment_method"), "-"),
        "reference": row.get("payment_reference"),
        "request_id": row["id"],
    }


def _send_paid_emails(row: dict) -> None:
    r = build_receipt(row)
    lines = [
        f"Receipt {r['receipt_no']}",
        f"Item: {r['item']}",
        f"Package price: GH₵{r['price']:,.2f}",
    ]
    if r["xera_discount"]:
        lines.append(f"XERA saving: -GH₵{r['xera_discount']:,.2f}")
    lines += [
        f"Total paid: GH₵{r['amount_paid']:,.2f}",
        f"Method: {r['method']}",
        f"Reference: {r['reference']}",
    ]
    body = "\n".join(lines)
    send_email(
        to=r["customer"]["email"],
        subject=f"Your EVOXERA receipt {r['receipt_no']}",
        body=(f"Hi {r['customer']['name']},\n\nThank you, your payment is confirmed.\n\n{body}\n\n"
              "Our team will be in touch about your website. You can follow up any time from the "
              "website-creation page on evoshub.xyz.\n\nEVOXERA TECHNOLOGY"),
    )
    send_email(
        to=os.getenv("ADMIN_NOTIFY_EMAIL", os.getenv("EMAIL_USER", "")),
        subject=f"PAID website order — {r['customer']['name']} ({r['item']})",
        body=f"{body}\n\nCustomer: {r['customer']['name']} <{r['customer']['email']}>\nRequest ID: {r['request_id']}\n",
    )


# ------------------------------------------------------------------------ uploads

_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
    (b"%PDF-", "application/pdf", "pdf"),
)


def sniff_file_type(head: bytes) -> tuple[str, str] | None:
    """(mime, extension) from the file's own first bytes, ignoring whatever the browser claimed."""
    for sig, mime, ext in _SIGNATURES:
        if head.startswith(sig):
            return mime, ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


async def save_upload(request_id: str, filename: str, content: bytes) -> dict:
    if not content:
        raise WebsiteOrderError("empty_file", "That file is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise WebsiteOrderError("file_too_large", "Each file must be 5 MB or smaller.", 413)
    kind = sniff_file_type(content[:16])
    if not kind:
        raise WebsiteOrderError("file_type", "Only images (PNG, JPG, WEBP, GIF) and PDFs are accepted.", 415)
    if await count_website_files(request_id) >= MAX_FILES:
        raise WebsiteOrderError("too_many_files", f"You can attach up to {MAX_FILES} files.", 409)

    mime, ext = kind
    storage_path = f"{request_id}/{uuid.uuid4().hex}.{ext}"
    display_name = clean_text(filename or f"file.{ext}")[:200] or f"file.{ext}"
    await upload_website_file(storage_path, content, mime)
    row = await insert_website_file_row({
        "request_id": request_id, "storage_path": storage_path,
        "file_name": display_name, "mime_type": mime, "size_bytes": len(content),
    })
    return {"id": row.get("id"), "file_name": display_name, "size_bytes": len(content), "mime_type": mime}
