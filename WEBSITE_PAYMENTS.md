# Website Creation: payments, receipts, uploads

Run first: `supabase/migrations/20261109_website_payments_uploads.sql` (Supabase SQL editor).

Prices (python/services/website_orders.py), cash price shown with the 50%-off list price: Starter GH₵500 (was 1,000), Business 1,000 (was 2,000), Premium 1,500 (was 3,000), WhatsApp bot 500 (was 1,000, placeholder, confirm). With XERA: Starter 400, Business 800, Premium 1,200, WhatsApp bot 400. Run supabase/migrations/20261110_whatsapp_bot_package.sql and 20261111_website_chat_repair.sql too.
XERA saving: 20% of the cash price (env `WEBSITE_XERA_DISCOUNT_PCT`). It follows the existing
XERA data-discount switch (`xera_discount_config.enabled`) and XERA-per-GHS rate.

Env to set on the backend:
- `XERA_PAYSTACK_SECRET_KEY` (Paystack on). Webhook URL stays `/api/xera/hashrate/webhooks/paystack`.
- `NOWPAYMENTS_API_KEY`, `NOWPAYMENTS_IPN_SECRET`, `XERA_NOWPAYMENTS_IPN_URL` (crypto on). IPN URL stays `/api/xera/hashrate/webhooks/nowpayments`.
- `WEBSITE_PAYMENT_RETURN_URL` = `https://evoshub.xyz/website-creation.html`
- Optional: `XERA_CRYPTO_GHS_PER_USD` fixed rate, `ADMIN_NOTIFY_EMAIL`.
