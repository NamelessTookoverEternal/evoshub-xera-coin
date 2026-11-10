# Website Creation: payments, receipts, uploads

Run first: `supabase/migrations/20261109_website_payments_uploads.sql` (Supabase SQL editor).

Prices (python/services/website_orders.py), all 50% off list: Starter GH₵400 (was 800), Business 900 (was 1,800), Premium 1,500 (was 3,000), WhatsApp bot 500 (was 1,000, placeholder, confirm). Run supabase/migrations/20261110_whatsapp_bot_package.sql too.
XERA saving: 10% of the cash price (env `WEBSITE_XERA_DISCOUNT_PCT`). It follows the existing
XERA data-discount switch (`xera_discount_config.enabled`) and XERA-per-GHS rate.

Env to set on the backend:
- `XERA_PAYSTACK_SECRET_KEY` (Paystack on). Webhook URL stays `/api/xera/hashrate/webhooks/paystack`.
- `NOWPAYMENTS_API_KEY`, `NOWPAYMENTS_IPN_SECRET`, `XERA_NOWPAYMENTS_IPN_URL` (crypto on). IPN URL stays `/api/xera/hashrate/webhooks/nowpayments`.
- `WEBSITE_PAYMENT_RETURN_URL` = `https://evoshub.xyz/website-creation.html`
- Optional: `XERA_CRYPTO_GHS_PER_USD` fixed rate, `ADMIN_NOTIFY_EMAIL`.
