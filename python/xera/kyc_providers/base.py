"""
KYC provider interface. A provider hosts the ID + selfie capture on ITS OWN page; our servers never
receive the images. Each adapter only (1) starts a hosted session for one of our attempts and
(2) authenticates + translates the provider's callback into one of our neutral statuses.

A provider result is NEVER "verified" by itself. The strongest thing a provider can say is APPROVED,
which only makes the case eligible for the final admin decision (see xera/kyc_provider.py).
"""

STARTED = "STARTED"        # session created, user has not finished
IN_REVIEW = "IN_REVIEW"    # provider wants a human look / result unclear
APPROVED = "APPROVED"      # provider's checks passed -> waits for the admin
DECLINED = "DECLINED"      # provider's checks failed
ABANDONED = "ABANDONED"    # user left or the session expired

PROVIDER_STATUSES = (STARTED, IN_REVIEW, APPROVED, DECLINED, ABANDONED)


class KycProviderError(Exception):
    """Short machine-readable code; routes map it to an HTTP response. Never carries secrets."""


class KycWebhookError(Exception):
    """The callback failed authentication or was malformed."""
