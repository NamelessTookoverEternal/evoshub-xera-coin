"""
XERA-specific Paystack integration for hashrate purchases.

There is no existing Paystack backend in this repository (EVOS Data
Services has its own, in a separate codebase, on its own
integer-user-id auth model — not reused here per the architecture
decision to avoid a second, cross-repo-coupled Paystack implementation).
This is a small, self-contained service scoped to XERA hashrate only.

Isolation from EVOSDATA: every reference this module generates is
prefixed `xera-hr-`, so even if the two products end up sharing the same
Paystack account/secret key, a XERA hashrate reference can never
collide with — or be confused for — an EVOSDATA order reference.

Security:
- References are always server-generated (uuid4), never client-supplied.
- Webhook signature verified with HMAC-SHA512 over the raw request body,
  compared with hmac.compare_digest (constant-time) — see Paystack's
  documented webhook verification scheme.
- verify() re-confirms the transaction against Paystack's API rather
  than trusting the webhook payload alone, so a forged webhook body
  still can't activate a session without a matching real transaction.
- Amount and currency are checked by the caller (hashrate.py) against
  the tier's price/currency at confirmation time — this module only
  reports what Paystack says was paid.
"""

import hashlib
import hmac
import os
import uuid

import httpx

from xera.payments.base import HashratePaymentProvider, PaymentProviderError

_PAYSTACK_BASE_URL = "https://api.paystack.co"
_REFERENCE_PREFIX = "xera-hr-"


def _secret_key() -> str:
    key = os.getenv("XERA_PAYSTACK_SECRET_KEY", "")
    if not key:
        raise RuntimeError("XERA_PAYSTACK_SECRET_KEY not configured.")
    return key


def new_reference() -> str:
    return f"{_REFERENCE_PREFIX}{uuid.uuid4().hex}"


def is_xera_hashrate_reference(reference) -> bool:
    return isinstance(reference, str) and reference.startswith(_REFERENCE_PREFIX)


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    if not signature_header:
        return False
    computed = hmac.new(_secret_key().encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature_header)


class PaystackHashrateProvider(HashratePaymentProvider):
    name = "PAYSTACK"

    def initialize(self, *, reference: str, amount, currency: str, user_id: int, metadata: dict, email: str | None = None) -> dict:
        # Paystack rejects /transaction/initialize without a customer email,
        # so without this every checkout failed with "Invalid Email Address".
        if not email:
            raise PaymentProviderError("customer_email_required")

        # Paystack amounts are in the currency's smallest unit (pesewas/kobo).
        amount_minor = int(round(float(amount) * 100))
        body = {
            "reference": reference,
            "email": email,
            "amount": amount_minor,
            "currency": currency,
            "metadata": {**metadata, "user_id": user_id, "product": "xera_hashrate"},
        }
        # Where Paystack sends the customer after checkout. The frontend reads
        # ?reference= on that page to switch to the Hashrate tab and wait for
        # the webhook to activate the session.
        callback_url = os.getenv("XERA_HASHRATE_CALLBACK_URL", "").strip()
        if callback_url:
            body["callback_url"] = callback_url
        try:
            resp = httpx.post(
                f"{_PAYSTACK_BASE_URL}/transaction/initialize",
                headers={"Authorization": f"Bearer {_secret_key()}"},
                json=body,
                timeout=15,
            )
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PaymentProviderError("paystack_unreachable") from e

        if not data.get("status"):
            raise PaymentProviderError(f"paystack_init_failed: {data.get('message')}")

        return {
            "authorization_url": data["data"]["authorization_url"],
            "access_code": data["data"]["access_code"],
            "reference": reference,
        }

    def verify(self, *, reference: str) -> dict:
        try:
            resp = httpx.get(
                f"{_PAYSTACK_BASE_URL}/transaction/verify/{reference}",
                headers={"Authorization": f"Bearer {_secret_key()}"},
                timeout=15,
            )
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PaymentProviderError("paystack_unreachable") from e

        if not data.get("status"):
            return {"confirmed": False, "tx_hash": None, "raw": data}

        tx = data.get("data", {})
        confirmed = tx.get("status") == "success"
        return {
            "confirmed": confirmed,
            "tx_hash": tx.get("id") and str(tx["id"]),
            "amount_minor": tx.get("amount"),
            "currency": tx.get("currency"),
            "raw": tx,
        }
