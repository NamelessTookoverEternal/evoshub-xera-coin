# XERA discount on EVOS Data (off by default)

Default deal: 4% off, paid for with XERA at 100 XERA = GH₵ 1.00, never more than 10% off.
GH₵ 5.00 bundle -> GH₵ 4.80 cash + 20 XERA. Signed-in users with enough spendable XERA. Users who have not done KYC get the same discount for 1.75x the XERA (35 instead of 20).

## Turn on (Supabase SQL Editor)
1. Run `supabase/migrations/20261107_xera_data_discount_v1.sql`, then `20261108_xera_discount_unverified_v1.sql` (safe to re-run; nothing changes for users yet).
2. Deploy the backend and the EVOS Data frontend.
3. When ready: `UPDATE xera_discount_config SET enabled = true, updated_at = now() WHERE id = 1;`
   Off again: same with `false`. The checkout toggle disappears when it is off.
4. Unverified price: `UPDATE xera_discount_config SET unverified_multiplier = 1.75 WHERE id = 1;` (1.5 = 30 XERA; 0 = KYC required again).
5. Change the deal: `UPDATE xera_discount_config SET xera_per_ghs = 100, discount_pct = 4, max_pct = 10 WHERE id = 1;`

## How it works
- Quote: `GET /xera-discount/quote` (needs the user's token). Create: `POST /orders/create` with `use_xera: true`.
- The server recomputes everything; the browser can never set a price or an XERA amount.
- Payment starts -> XERA is HELD for that order (30 min). Paystack confirms -> held XERA becomes a DISCOUNT_SPEND debit in the XERA ledger.
  Never paid -> the hold is released (the 30-minute failed-order sweep also does this).
- Late payment, or the balance dropped meanwhile: the discount is still honoured; what XERA is left is debited and the gap is recorded in `xera_discount_holds.shortfall`.
- Spent XERA leaves the user's balance and is not returned to the mining pool. XERA spent can never be claimed on-chain (claimable is capped at the wallet balance).
- Refund an order's XERA by hand: `SELECT xera_discount_refund('<paystack reference>');` (not automatic).
- Checks: `SELECT * FROM xera_discount_holds ORDER BY id DESC LIMIT 20;`, and `late = true` or `shortfall > 0` rows.

## Before you switch it on
- The Miner Agreement, the XERA disclosure and the CoinGecko wording say XERA has no monetary value. The checkout says "Promotional discount" and the rate is a setting, not a price, but add one line to the agreement and disclosure saying XERA may be used for promotional discounts in EVOS products. If you change the agreement, bump `AGREEMENT_VERSION` and `xera_launch_config.agreement_version` together.
- Show it on the roadmap as PLANNED until the switch is on.
