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
