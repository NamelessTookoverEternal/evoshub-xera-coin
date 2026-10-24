# XERA dashboard: KYC, first-transfer fee, notifications

## What is implemented (and tested)
| Piece | Where |
|---|---|
| SQL migration (3 new tables, RLS, service-role only) | `supabase/migrations/20261024_xera_kyc_fee_readiness_v1.sql` |
| Readiness logic + server gate | `python/xera/readiness.py` |
| `GET /api/xera/readiness`, `POST /api/xera/kyc/submit` | `python/xera/routes_readiness.py` |
| Admin review: `GET /api/admin/xera/kyc/pending`, `POST /api/admin/xera/kyc/{user_id}/review` | same file |
| Gate on `/claim/sign-amount`, `/claim/retry`, legacy `sign_claim`, `/migration/claim/prepare` | `python/xera/chain/claims.py`, `migration.py`, `routes_chain.py` |
| Pilot exemption helper | `python/xera/chain/config.py` (`admin_pilot_active`) |
| Dashboard cards + 3 dialogs | `hub-frontend/src/js/xera-readiness.js`, `css/xera-readiness.css`, `pages/xera/index.html`, hooks in `xera.js` / `xera-chain.js` |
| Tests | `python/tests/test_readiness.py` (23), `conftest.py` helper |

Card 1 (mining timer) is the existing card, unchanged. Mining, balances, rewards, 25/75 split, referrals and TON/BNB claim logic are untouched.

## Admin pilot
Exempt from the KYC/fee gate only while `XERA_ADMIN_ONCHAIN_PILOT=true` AND inside the admin pilot route.
Set it to `false` on Render after the successful mainnet test: admins are then gated like users and the pilot routes refuse. No code change needed.

## Run before deploying (manual)
1. Supabase SQL editor: run `20261024_xera_kyc_fee_readiness_v1.sql` (additive, re-runnable). Run the verify SELECTs at the bottom.
2. Deploy backend (Render), then frontend.
3. Until step 1 is done every user shows "Unverified / Unpaid" and transfers stay blocked (the gate fails closed).

## Env vars (all optional, safe defaults)
- `XERA_TRANSFER_FEE_AMOUNT_MINOR` (default `100`), `XERA_TRANSFER_FEE_CURRENCY` (default `USD`)
- `XERA_FEE_COLLECTION_ENABLED` (default `false`; display only today, see blockers)

## NOT implemented / blockers
- **Fee payment**: no charge route and no fee webhook exist, so the fee can never become PAID yet. Needs: Paystack USD enabled (check the dashboard's currency list), refund policy + consumer disclosure, and a webhook that verifies the signature, re-verifies with Paystack, checks amount AND currency, and writes PAID once (`UNIQUE(payment_reference)` stops duplicates).
- **KYC provider**: none configured. Current flow = manual admin review, no ID images, only the last 4 characters of the ID kept. There is **no admin review screen yet**, only the API above.
- No audited admin "waive fee" action (not built).
- Persistent notifications exist only for KYC decisions; the rest are derived live from server state.

## Tests
- 23 new tests pass, plus all existing claim/wallet/pilot tests; no regressions versus the original repo.
- The same 37 tests fail before and after my changes (evosdata, referrals, launch-session tests that need the real app/env).
- NOT run: real Postgres checks of the new constraints/RLS, duplicate-webhook test (no webhook yet), Paystack test-mode payment, Hardhat/TON suites, mainnet-disabled check against a real `xera_chain_config`.
