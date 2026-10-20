-- ============================================================================
-- XERA OFFICIAL LAUNCH — ROLLBACK OF THE RESET   (MANUAL, OWNER-RUN, OPTIONAL)
-- ============================================================================
-- Restores the pre-reset test data from schema xera_backup_launch_reset.
-- ONLY valid BEFORE launch activity starts. It refuses to run if any ledger
-- rows, sessions or early-miner bonuses exist (restoring would destroy them).
-- It never deletes the backup schema. To run, change the confirmation word.
--
-- Restores: xera_transactions, xera_mining_sessions, wallet balances,
--           daily-claim progress, mining_distributed, entitlement ledger.
-- Does not touch: users, wallets' identities, hashrate/referral/on-chain data
--           (the reset never changed those).
-- ============================================================================
BEGIN;
SET LOCAL lock_timeout = '15s';

DO $$
DECLARE
    v_confirm TEXT := 'NO';     -- <<< change to 'YES-ROLLBACK-XERA-RESET' to run
BEGIN
    IF v_confirm IS DISTINCT FROM 'YES-ROLLBACK-XERA-RESET' THEN
        RAISE EXCEPTION 'Rollback not confirmed. Nothing was changed.';
    END IF;
    IF to_regnamespace('xera_backup_launch_reset') IS NULL THEN
        RAISE EXCEPTION 'No backup schema found. Nothing was changed.';
    END IF;
    IF EXISTS (SELECT 1 FROM xera_transactions) OR EXISTS (SELECT 1 FROM xera_mining_sessions)
       OR EXISTS (SELECT 1 FROM xera_early_miner_bonuses) THEN
        RAISE EXCEPTION 'Launch activity already exists; rolling back would destroy it. Nothing was changed.';
    END IF;
END $$;

LOCK TABLE xera_launch_state, xera_mining_entitlement_state, xera_allocations,
           xera_wallets, xera_transactions, xera_mining_sessions, xera_daily_claims
    IN ACCESS EXCLUSIVE MODE;

INSERT INTO xera_transactions SELECT * FROM xera_backup_launch_reset.xera_transactions;
INSERT INTO xera_mining_sessions SELECT * FROM xera_backup_launch_reset.xera_mining_sessions;

UPDATE xera_wallets w SET cached_balance = b.cached_balance, updated_at = now()
  FROM xera_backup_launch_reset.xera_wallets b WHERE b.id = w.id;

UPDATE xera_daily_claims d
   SET last_claim_date = b.last_claim_date, streak = b.streak, total_claims = b.total_claims, updated_at = now()
  FROM xera_backup_launch_reset.xera_daily_claims b WHERE b.user_id = d.user_id;

UPDATE xera_allocations a SET mining_distributed = b.mining_distributed, updated_at = now()
  FROM xera_backup_launch_reset.xera_allocations b WHERE b.id = a.id;

UPDATE xera_mining_entitlement_state e
   SET reserved_amount = b.reserved_amount, free_mining_closed = b.free_mining_closed, updated_at = now()
  FROM xera_backup_launch_reset.xera_mining_entitlement_state b WHERE b.id = e.id;

DO $$
DECLARE m xera_backup_launch_reset.backup_meta;
BEGIN
    SELECT * INTO m FROM xera_backup_launch_reset.backup_meta;
    IF (SELECT COUNT(*) FROM xera_transactions) <> m.transactions
       OR (SELECT COUNT(*) FROM xera_mining_sessions) <> m.sessions
       OR (SELECT COALESCE(SUM(cached_balance),0) FROM xera_wallets) <> m.wallet_balance_sum
       OR (SELECT mining_distributed FROM xera_allocations WHERE id = 1) <> m.mining_distributed
       OR (SELECT reserved_amount FROM xera_mining_entitlement_state WHERE id = 1) <> m.reserved_amount THEN
        RAISE EXCEPTION 'Rollback verification failed. Rolled back the rollback.';
    END IF;
END $$;

COMMIT;
