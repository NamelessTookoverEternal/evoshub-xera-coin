"""
Crypto payment-IN provider for hashrate — DISABLED by design.

Per the architecture decision for this feature: the existing chain
infrastructure (xera/chain/*) handles outgoing XERA claim settlement
(mining balance -> on-chain claim), not incoming payments. There is no
treasury address, confirmation policy, or asset/chain selection agreed
yet, so this module intentionally does not implement one — inventing a
payment watcher here would be exactly the kind of scope creep the brief
warns against ("do not invent a treasury/payment watcher").

This class exists so routes_hashrate.py / hashrate.py can reference
CRYPTO as a payment_method in the schema and reject it with a clear,
typed error, rather than the method silently not existing. Flip
XERA_HASHRATE_CRYPTO_ENABLED=true only once chain/asset/treasury/
confirmation policy are explicitly configured AND a real verify()
implementation (checking an on-chain deposit, not trusting the
frontend) replaces the NotImplementedError below.
"""

import os

from xera.payments.base import HashratePaymentProvider, PaymentProviderError


def crypto_payments_enabled() -> bool:
    return os.getenv("XERA_HASHRATE_CRYPTO_ENABLED", "false").strip().lower() == "true"


class CryptoHashrateProvider(HashratePaymentProvider):
    name = "CRYPTO"

    def initialize(self, *, reference: str, amount, currency: str, user_id: int, metadata: dict, email: str | None = None) -> dict:
        raise PaymentProviderError("crypto_payments_not_yet_configured")

    def verify(self, *, reference: str) -> dict:
        raise PaymentProviderError("crypto_payments_not_yet_configured")
