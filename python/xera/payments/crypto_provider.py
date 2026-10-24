"""
Crypto payment-IN provider for hashrate: USDT (BEP-20) through NOWPayments.

The decision that was open before — chain, asset, treasury — is now made:
  * chain/asset: USDT on BNB Smart Chain
  * treasury:    a dedicated receive-only BNB wallet set as the payout address in
                 the NOWPayments dashboard (non-custodial). Not the deployer, signer
                 or any user wallet, and its key never touches this backend.
  * confirmation: NOWPayments reports `finished`, and we re-verify it ourselves
                 against their API before activating anything
                 (see xera/payments/nowpayments_provider.py).

Crypto stays OFF until XERA_HASHRATE_CRYPTO_ENABLED=true AND the NOWPayments API
key and IPN secret are present, so a half-configured environment can never show a
Buy button that cannot work.
"""

import os

from xera.payments.nowpayments_provider import NowPaymentsProvider, configured


def crypto_payments_enabled() -> bool:
    flag = os.getenv("XERA_HASHRATE_CRYPTO_ENABLED", "false").strip().lower() == "true"
    return flag and configured()


class CryptoHashrateProvider(NowPaymentsProvider):
    name = "CRYPTO"
