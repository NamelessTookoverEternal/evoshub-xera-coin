# XERA official launch — database runbook (Batch 1)

Nothing here runs automatically. The owner runs each SQL file by hand in the
Supabase SQL Editor of the **production** project, in this order:

| # | File | Type | Effect |
|---|------|------|--------|
| 1 | `migrations/20261021_xera_official_launch_v1.sql` | migration | Adds tables/functions. Changes no balances. Bonus ships **disabled**. Safe to re-run. |
| 2 | `operations/xera_official_launch_reset.sql` | manual, one-time | Backs up, then resets test data. **Edit the confirmation word first.** |
| 3 | `operations/xera_official_launch_final_update.sql` | manual | Daily reward = 2, enables the first-100 promotion, publishes versions. |
| – | `operations/xera_official_launch_rollback.sql` | manual, optional | Restores the pre-reset data. Refuses once any launch activity exists. |

`operations/xera_official_test_reset.sql` is the old script (it paid 100 XERA to
every wallet). It now fails on purpose. Do not run it.

## Deployment sequence
1. Deploy the backend/frontend (Batches 2 and 3) **before** step 2 below, because the
   migration makes the database refuse to start mining without an accepted agreement.
   Applying it with the old backend means Start Mining errors until the new backend is live.
2. Apply the migration (step 1). 3. Run the reset (step 2). 4. Run the final update (step 3).
5. Verify: `SELECT xera_launch_status(), xera_launch_reconcile();` — `reconcile.ok` must be `true`.

## What the reset does
* Backs up 10 tables into schema `xera_backup_launch_reset` (private; RLS on; no
  anon/authenticated access). Backups are never deleted by any script.
* Deletes `xera_transactions` and `xera_mining_sessions` (no foreign key points at
  either, so this is safe). Sets every `cached_balance` to 0. Clears daily-claim
  streak/count/date (rows kept). Sets `mining_distributed` to 0.
* Re-bases `xera_mining_entitlement_state.reserved_amount` to the capacity still held
  by **paid** hashrate sessions (`reserved_entitlement - rewarded_amount`), because the
  old script's blind zero would have let the 75M cap be exceeded.
* One transaction. A failed precondition or verification rolls everything back.
* Aborts if: confirmation word unchanged, schema objects missing, backups exist
  (already run), supply/allocation is not 500M/75M, any early-miner bonus exists,
  or `xera_onchain_claims` has rows.

## Preserved on purpose (owner decisions)
* **Hashrate sessions/payments** are financial records and are kept. Their already-paid
  rewards disappear from the ledger with the reset. Clearing them is a separate decision.
* **Referral links** are kept; referral rewards in the old ledger are gone. Referral
  payouts do not count against the 75M pool in the current design (pre-existing).
* **On-chain claims**: reset aborts if any exist, because `xera_claimable_balance`
  subtracts every historical claim and would permanently shrink launch users' claimable amount.

## Accounting design for the bonus
`mining_distributed` and `entitlement.reserved_amount` both include bonuses (same as daily
claims). Bonuses are also tracked in `xera_launch_state.bonus_distributed`
(`regular_rewards = mining_distributed - bonus_distributed`). The 100 x 100 limit is enforced by
CHECK constraints, a unique slot number, one row per user, and a row-locked counter.
Eligibility = the first 100 accounts whose mining session is **successfully created** after
accepting the current agreement; bonus is evaluated after the session exists, in the same
transaction, so a failed start never consumes a slot. If crediting would exceed the 75M
allocation the bonus is skipped (`SKIPPED_ALLOCATION`) and the session still starts.

Note: `BONUS` credits are not in the on-chain claimable formula (`MINING_REWARD` + `DAILY_CLAIM`
only), so the 100 XERA bonus is not claimable on-chain unless that is changed in the future
claiming phase. On-chain claiming is out of scope here.

## Rollback
Before launch activity: run `xera_official_launch_rollback.sql` (confirmation word again).
After launch activity: not supported by script — restore selectively from
`xera_backup_launch_reset.*`. The backup schema must be dropped manually (and only deliberately)
before the reset can be run a second time.

## Tests (all run against real Postgres 16, disposable DBs)
`supabase/tests/run_launch_tests.sh`, `run_launch_reset_test.sh`, `run_launch_concurrency_test.sh`.
