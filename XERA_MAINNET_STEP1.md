# XERA mainnet readiness — step 1 (backend, database, tests)

Nothing here deploys a contract, moves tokens or changes tokenomics (500M supply, 75M mining pool, $1 fee untouched).

## What changed
| Audit item | Fix | File |
|---|---|---|
| C1 amount precision | One exact `Decimal` wei conversion for sign, confirm and retry (float removed) | `python/xera/chain/claims.py` |
| C2 testnet vs mainnet | Every claim is stamped `network`; the 75M on-chain cap counts mainnet claims only; a claim can't be confirmed/retried on another network | `claims.py`, `config.py` (`onchain_network`), migration |
| C5 verifier | RPC chain id must match the app; claim must have N confirmations (default 1 testnet / 5 mainnet) | `python/xera/chain/onchain_indexer.py` |
| C6 status drift | Only a proven-reverted tx marks a claim FAILED; pending/unclear results leave the reservation alone | `claims.py` |
| UX | Claim page retries the confirm call for ~1 min while confirmations accrue | `hub-frontend/src/js/xera-chain.js` |

## Run order on deploy
1. Run `supabase/migrations/20261030_xera_mainnet_readiness_v1.sql` (idempotent). All existing claim rows become `testnet`. Nothing is deleted or reversed.
2. Deploy the backend + frontend. Behaviour on testnet (chain 97) is unchanged.

## New optional env var (public, not secret)
`XERA_BNB_CONFIRMATIONS` — blocks required before a claim is recorded. Default 1 on chain 97, 5 on chain 56.

## Note
Balances debited by earlier testnet claims stay debited (no data was reset). If you want them credited back before mainnet, that is a separate, explicit decision.
