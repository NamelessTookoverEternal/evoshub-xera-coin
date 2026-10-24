# XERA — USDT (BEP-20) payments via NOWPayments

Main payment rail for XERA hashrate plans and the one-time $1 first-transfer fee.
Paystack stays as the alternative for hashrate. TON claims stay greyed out.

## 1. NOWPayments dashboard (once)

1. Create the account. Confirm a Ghana-based business can sign up and receive payouts,
   and check the minimum payment for USDT on BNB Smart Chain (a $1 fee may sit below it).
2. Payout wallet: create a **fresh BNB wallet used only for receiving**. Not wallets 1–3.
   Add it as the payout address for **USDT (BSC)** and turn on auto-withdraw to it.
   Do **not** enable the custody option. Its key never goes in this backend.
3. Create an **API key** and an **IPN secret**.
4. In the dashboard, set the IPN callback to:
   `https://<your-render-backend>/api/xera/hashrate/webhooks/nowpayments`
   (one URL serves both hashrate purchases and the fee).

## 2. Render environment variables (never paste these in chat or commit them)

| Variable | Value |
|---|---|
| `NOWPAYMENTS_API_KEY` | from the dashboard |
| `NOWPAYMENTS_IPN_SECRET` | from the dashboard |
| `XERA_NOWPAYMENTS_IPN_URL` | same URL as in step 4 above |
| `XERA_HASHRATE_CRYPTO_ENABLED` | `true` (stays off until you flip it) |
| `XERA_CRYPTO_SUCCESS_URL` | `https://evoshub.xyz/xera/?pay=crypto` |
| `XERA_FEE_SUCCESS_URL` | `https://evoshub.xyz/xera/?fee=return` |
| `XERA_FEE_COLLECTION_ENABLED` | `true` when you want the $1 fee open |
| `XERA_CRYPTO_GHS_PER_USD` | optional fixed rate, e.g. `15`. Unset = live rate |
| `NOWPAYMENTS_SANDBOX` | `true` to test against NOWPayments' sandbox first |
| `XERA_NOWPAYMENTS_PAY_CURRENCY` | optional, defaults to `usdtbsc` |

Crypto only shows as available when the flag is `true` **and** both the API key and IPN
secret are set.

## 3. Database

Run `supabase/migrations/20261025_xera_crypto_payments_v1.sql` in the Supabase SQL editor
(adds two columns and replaces the confirm function so crypto amounts are checked).
Run it **before** turning crypto on.

## How the money is protected

- Hashrate prices are in GHS. At purchase the backend converts to USD once (rounded up to
  the cent) and stores that exact figure on the payment row.
- The webhook is only a trigger. A `finished` notice makes the backend re-read the payment
  from NOWPayments' API and check: finished, our order id, USDT-BSC, and that the price
  matches the stored figure (database-enforced). Anything else leaves the session unpaid.
- A NOWPayments payment id can activate only one session. Replays are harmless.
- Paid but allocation full, or the fee paid twice: logged as CRITICAL for a manual refund.
- Partially paid invoices do nothing until the customer tops up.

## Test first (sandbox)

Set `NOWPAYMENTS_SANDBOX=true` with sandbox keys, buy the smallest tier, and watch the
Render logs for the webhook. Switch to live keys only after one full purchase and one fee
payment work end to end.
