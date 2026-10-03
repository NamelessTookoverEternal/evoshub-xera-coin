# XERA Token (Coin) V1 Integration

This package contains only the EVOS Business Hub project with XERA Token (Coin) integrated at `/xera`.

## Active V1
- XERA-only user login using the shared public `users` table
- Independent XERA wallet and ledger
- Server-authoritative 24-hour mining
- Atomic reward claim
- Transaction history
- XERA admin API

## Disabled V1
- Fiat purchase
- Withdrawal
- Transfer
- Referral rewards
- Exchange/listing integration
- On-chain migration

## Deployment checklist
1. Configure Python environment variables from `python/.env.example`.
2. Install backend dependencies from `python/requirements.txt`.
3. Review and run `supabase/migrations/20260901_xera_token_v1.sql` in the shared Supabase project. Confirm `public.users.id` is BIGINT before applying this migration.
4. Deploy the existing EVOS Hub backend and frontend using their current production configuration.
5. Point `api.evoshub.xyz` to the EVOS Hub backend, or set `window.XERA_API_BASE` before loading the XERA frontend if a different API host is used.
6. Verify `/xera`, login, wallet, mining start and claim in a staging environment before public release.

No EVOS Data Services, EVOSGPT, or standalone XERA project is included in this package.

## Referrals (V1.2)
- Identity lives on the shared `users` row: `referral_code` (my code) and `referred_by` (who invited me, set once, first touch wins). EVOSGPT and EVOS Data already write both, so a referral made in any product is attributed in every product.
- Invite link: `https://evoshub.xyz/xera/invite?ref=CODE` → install the app → create account with the code pre-filled. Override the base with `XERA_INVITE_BASE_URL` on the backend.
- Run `supabase/migrations/20260930_xera_referrals_v1.sql` (backfills a code for every user that lacks one, adds the unique index, `xera_link_referral`, `xera_qualify_referral`).
- Rewards are OFF until you set amounts in `xera_referral_config` AND `xera_config.referral_enabled = true`. A referral qualifies on the referred user's first completed mining claim.
- API: `GET /api/xera/referral/validate?code=`, `GET /api/xera/referral/me`; `POST /api/xera/auth/register` accepts optional `ref`.
- Tests: `python/tests/test_referrals.py`, `supabase/tests/test_referrals.sql`.
