"""
NOWPayments (USDT on BNB Smart Chain, BEP-20) — payment-IN rail for XERA.

Used for two things, both XERA-only and both priced in USD:
  * hashrate plans (reference prefix `xera-hr-`, shared with Paystack)
  * the one-time first-transfer processing fee (reference prefix `xera-fee-`)

Money flow: NOWPayments is used NON-CUSTODIALLY. The payout wallet (a fresh BNB
address that is not one of the deployer/signer/user wallets) and "auto-withdraw to
my wallet" are configured in the NOWPayments dashboard, never in this code.

Trust model (same as the Paystack provider):
  * References are server-generated; the client never supplies one.
  * An IPN (webhook) is authenticated by HMAC-SHA512 over the key-sorted JSON body
    with NOWPAYMENTS_IPN_SECRET (header `x-nowpayments-sig`), compared in constant time.
  * The IPN body is NEVER trusted for money. verify() re-reads the payment from
    NOWPayments' API with our API key and checks: status == finished, order_id ==
    our reference, pay_currency == USDT-BEP20, and returns the price NOWPayments
    recorded so the database can compare it with what we stored at purchase time.
"""

import hashlib
import hmac
import json
import logging
import os
from decimal import ROUND_CEILING, Decimal, InvalidOperation

import httpx

from xera.payments.base import HashratePaymentProvider, PaymentProviderError

logger = logging.getLogger(__name__)

_LIVE_BASE = "https://api.nowpayments.io/v1"
_SANDBOX_BASE = "https://api-sandbox.nowpayments.io/v1"

ASSET_LABEL = "USDT-BEP20"
CHARGE_CURRENCY = "USD"

# Statuses NOWPayments documents for a payment.
PAID_STATUS = "finished"
FAILED_STATUSES = ("failed", "refunded")
EXPIRED_STATUS = "expired"


def _api_key() -> str:
    key = os.getenv("NOWPAYMENTS_API_KEY", "").strip()
    if not key:
        raise PaymentProviderError("nowpayments_not_configured")
    return key


def _ipn_secret() -> str:
    secret = os.getenv("NOWPAYMENTS_IPN_SECRET", "").strip()
    if not secret:
        raise PaymentProviderError("nowpayments_not_configured")
    return secret


def _base_url() -> str:
    return _SANDBOX_BASE if os.getenv("NOWPAYMENTS_SANDBOX", "false").strip().lower() == "true" else _LIVE_BASE


def pay_currency() -> str:
    """NOWPayments ticker for USDT on BSC. Overridable in case NOWPayments renames it."""
    return (os.getenv("XERA_NOWPAYMENTS_PAY_CURRENCY", "usdtbsc") or "usdtbsc").strip().lower()


def configured() -> bool:
    return bool(os.getenv("NOWPAYMENTS_API_KEY", "").strip() and os.getenv("NOWPAYMENTS_IPN_SECRET", "").strip())


# ------------------------------------------------------------ pricing

def to_charge(price, currency: str) -> tuple[int, str]:
    """
    Convert a tier price (stored in GHS) to the USD amount we ask NOWPayments for, in
    cents, rounded UP so a rate wobble never under-charges. Returns (cents, "USD").

    Rate: XERA_CRYPTO_GHS_PER_USD if set (a fixed rate you control), otherwise the live
    rate already used for display pricing. If neither is available we refuse rather than
    invent a price.
    """
    try:
        amount = Decimal(str(price))
    except InvalidOperation as e:
        raise PaymentProviderError("crypto_bad_price") from e
    if amount <= 0:
        raise PaymentProviderError("crypto_bad_price")

    ccy = (currency or "").upper()
    if ccy == "USD":
        usd = amount
    elif ccy == "GHS":
        fixed = os.getenv("XERA_CRYPTO_GHS_PER_USD", "").strip()
        if fixed:
            try:
                ghs_per_usd = Decimal(fixed)
            except InvalidOperation as e:
                raise PaymentProviderError("crypto_rate_unavailable") from e
            if ghs_per_usd <= 0:
                raise PaymentProviderError("crypto_rate_unavailable")
            usd = amount / ghs_per_usd
        else:
            from services.evosgpt import currency as fx  # lazy: pulls in `requests`
            rates = fx._load_rates()
            usd_per_ghs = rates.get("USD") if rates else None
            if not isinstance(usd_per_ghs, (int, float)) or usd_per_ghs <= 0:
                raise PaymentProviderError("crypto_rate_unavailable")
            usd = amount * Decimal(str(usd_per_ghs))
    else:
        raise PaymentProviderError("crypto_currency_unsupported")

    cents = int((usd * 100).to_integral_value(rounding=ROUND_CEILING))
    if cents < 1:
        raise PaymentProviderError("crypto_bad_price")
    return cents, CHARGE_CURRENCY


# ------------------------------------------------------------ IPN signature

def _sort_keys(obj):
    if isinstance(obj, dict):
        return {k: _sort_keys(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_sort_keys(v) for v in obj]
    return obj


def verify_ipn_signature(raw_body: bytes, signature_header: str) -> bool:
    """HMAC-SHA512 of the key-sorted, compact JSON body (NOWPayments' documented scheme)."""
    if not signature_header:
        return False
    try:
        parsed = json.loads(raw_body)
    except (ValueError, TypeError):
        return False
    canonical = json.dumps(_sort_keys(parsed), separators=(",", ":"), ensure_ascii=False)
    computed = hmac.new(_ipn_secret().encode(), canonical.encode(), hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature_header.strip().lower())


# ------------------------------------------------------------ provider

def _urls_for(product: str) -> tuple[str, str]:
    """(success_url, cancel_url) for where NOWPayments sends the customer back."""
    if product == "xera_transfer_fee":
        success = os.getenv("XERA_FEE_SUCCESS_URL", "").strip()
        cancel = os.getenv("XERA_FEE_CANCEL_URL", "").strip() or success
    else:
        # Where the customer lands after paying, e.g. https://evoshub.xyz/xera/?pay=crypto
        success = os.getenv("XERA_CRYPTO_SUCCESS_URL", "").strip() or os.getenv("XERA_HASHRATE_CALLBACK_URL", "").strip()
        cancel = os.getenv("XERA_CRYPTO_CANCEL_URL", "").strip() or success
    return success, cancel


def _ipn_url() -> str:
    return os.getenv("XERA_NOWPAYMENTS_IPN_URL", "").strip()


class NowPaymentsProvider(HashratePaymentProvider):
    name = "CRYPTO"

    def initialize(self, *, reference: str, amount, currency: str, user_id: int, metadata: dict, email: str | None = None) -> dict:
        """`amount`/`currency` are the USD charge (already converted by to_charge)."""
        if (currency or "").upper() != CHARGE_CURRENCY:
            raise PaymentProviderError("crypto_currency_unsupported")
        ipn_url = _ipn_url()
        if not ipn_url:
            # Without it we would never hear about the payment.
            raise PaymentProviderError("nowpayments_not_configured")

        product = metadata.get("product", "xera_hashrate")
        success_url, cancel_url = _urls_for(product)
        body = {
            "price_amount": float(Decimal(str(amount)).quantize(Decimal("0.01"))),
            "price_currency": CHARGE_CURRENCY.lower(),
            "pay_currency": pay_currency(),
            "order_id": reference,
            "order_description": "XERA transfer processing fee" if product == "xera_transfer_fee" else "XERA hashrate",
            "ipn_callback_url": ipn_url,
        }
        if success_url:
            body["success_url"] = success_url
        if cancel_url:
            body["cancel_url"] = cancel_url

        try:
            resp = httpx.post(
                f"{_base_url()}/invoice",
                headers={"x-api-key": _api_key(), "Content-Type": "application/json"},
                json=body,
                timeout=20,
            )
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PaymentProviderError("nowpayments_unreachable") from e

        invoice_url = data.get("invoice_url") if isinstance(data, dict) else None
        if resp.status_code >= 400 or not isinstance(invoice_url, str) or not invoice_url.startswith("https://"):
            raise PaymentProviderError(f"nowpayments_init_failed: {resp.status_code} {data.get('message') if isinstance(data, dict) else ''}")

        return {
            "invoice_url": invoice_url,
            "invoice_id": str(data.get("id")),
            "reference": reference,
            "asset": ASSET_LABEL,
            "price_amount": body["price_amount"],
            "price_currency": CHARGE_CURRENCY,
        }

    def verify(self, *, reference: str, payment_id=None) -> dict:
        """
        Re-read the payment from NOWPayments. `payment_id` comes from the IPN body; it is
        only a lookup key — everything that decides success is read back from the API.
        """
        if not payment_id:
            return {"confirmed": False, "tx_hash": None, "raw": {"error": "no_payment_id"}}
        try:
            resp = httpx.get(
                f"{_base_url()}/payment/{payment_id}",
                headers={"x-api-key": _api_key()},
                timeout=20,
            )
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PaymentProviderError("nowpayments_unreachable") from e

        if resp.status_code >= 400 or not isinstance(data, dict):
            return {"confirmed": False, "tx_hash": None, "raw": data if isinstance(data, dict) else {}}

        status = str(data.get("payment_status", "")).lower()
        order_ok = data.get("order_id") == reference
        asset_ok = str(data.get("pay_currency", "")).lower() == pay_currency()
        confirmed = status == PAID_STATUS and order_ok and asset_ok

        try:
            amount_minor = int((Decimal(str(data.get("price_amount"))) * 100).to_integral_value())
        except (InvalidOperation, TypeError):
            amount_minor = None

        if status == PAID_STATUS and not (order_ok and asset_ok):
            logger.error("NOWPayments payment %s is finished but order_id/pay_currency mismatch (ref=%s)", payment_id, reference)

        return {
            "confirmed": confirmed,
            "status": status,
            "tx_hash": f"np-{payment_id}",
            "amount_minor": amount_minor,
            "currency": str(data.get("price_currency", "")).upper() or None,
            "raw": data,
        }
