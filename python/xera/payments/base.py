"""
HashratePaymentProvider abstraction.

Hashrate can be paid for through more than one rail (Paystack today,
crypto later), but both must ultimately activate the exact same
xera_hashrate_sessions / xera_hashrate_payments rows via
xera.hashrate.confirm_payment(). This module defines the shared
interface so xera/hashrate.py never branches on payment method beyond
"which provider do I ask to initialize/verify".
"""

from abc import ABC, abstractmethod


class PaymentProviderError(Exception):
    """Short machine-readable code; routes_hashrate.py maps these to HTTP responses."""


class HashratePaymentProvider(ABC):
    name: str

    @abstractmethod
    def initialize(self, *, reference: str, amount, currency: str, user_id: int, metadata: dict, email: str | None = None) -> dict:
        """Start the payment on the provider's side. Returns whatever the
        client needs to complete payment (e.g. a Paystack authorization_url,
        or a crypto deposit address + expected amount)."""

    @abstractmethod
    def verify(self, *, reference: str) -> dict:
        """Server-side verification (never trust a frontend 'success' flag).
        Returns {"confirmed": bool, "tx_hash": str | None, "raw": dict}."""
