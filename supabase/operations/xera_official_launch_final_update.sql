-- ============================================================================
-- XERA OFFICIAL LAUNCH — FINAL CONFIGURATION UPDATE   (MANUAL, OWNER-RUN)
-- ============================================================================
-- Run AFTER: backend deployed, migration 20261021 applied, and
--            operations/xera_official_launch_reset.sql completed successfully.
-- Idempotent. Does NOT delete or reset anything and does NOT touch balances,
-- sessions, the 500,000,000 supply or the 75,000,000 mining allocation.
--
-- It does exactly three things:
--   1. sets the daily-claim reward to 2 XERA            (xera_daily_config)
--   2. enables the first-100-miners promotion: max 100 recipients x 100 XERA
--      = 10,000 XERA, paid out of the existing 75M mining allocation
--   3. publishes the current agreement + welcome-notice versions
-- Keep the two version strings identical to the ones shipped by the backend
-- (python/xera/agreement.py). Changing a version later forces users to re-accept
-- / re-see it.
-- ============================================================================
BEGIN;
SET LOCAL lock_timeout = '15s';

DO $$
DECLARE
    v_alloc xera_allocations;
BEGIN
    IF to_regclass('public.xera_launch_config') IS NULL OR to_regclass('public.xera_launch_state') IS NULL THEN
        RAISE EXCEPTION 'Launch migration (20261021_xera_official_launch_v1.sql) is not applied. Nothing was changed.';
    END IF;
    IF to_regnamespace('xera_backup_launch_reset') IS NULL THEN
        RAISE EXCEPTION 'The reset has not been run (no backup schema). Run xera_official_launch_reset.sql first, so the bonus is not enabled on test data. Nothing was changed.';
    END IF;
    SELECT * INTO v_alloc FROM xera_allocations WHERE id = 1;
    IF v_alloc.total_target <> 500000000 OR v_alloc.mining_allocation <> 75000000 THEN
        RAISE EXCEPTION 'Unexpected supply/allocation (total %, mining %). Nothing was changed.', v_alloc.total_target, v_alloc.mining_allocation;
    END IF;
END $$;

-- 1. Daily claim reward = 2 XERA (the claim function reads this row on every claim)
UPDATE xera_daily_config SET reward_amount = 2, updated_at = now() WHERE id = 1;

-- 2 + 3. Promotion + versions
UPDATE xera_launch_config
   SET bonus_enabled          = true,
       bonus_max_recipients   = 100,
       bonus_amount           = 100,
       bonus_pool_cap         = 10000,
       agreement_version      = 'xera-miner-agreement-2026-10-v1',
       welcome_notice_version = 'xera-official-launch-2026-10-v1',
       updated_at             = now()
 WHERE id = 1;

DO $$
DECLARE v_rec JSONB;
BEGIN
    IF (SELECT reward_amount FROM xera_daily_config WHERE id = 1) <> 2 THEN
        RAISE EXCEPTION 'Verify failed: daily reward is not 2';
    END IF;
    IF NOT (SELECT bonus_enabled AND bonus_max_recipients = 100 AND bonus_amount = 100 AND bonus_pool_cap = 10000
              FROM xera_launch_config WHERE id = 1) THEN
        RAISE EXCEPTION 'Verify failed: bonus configuration';
    END IF;
    v_rec := xera_launch_reconcile();
    IF NOT (v_rec->>'ok')::boolean THEN
        RAISE EXCEPTION 'Verify failed: reconciliation problems: %', v_rec->'problems';
    END IF;
END $$;

COMMIT;

SELECT xera_launch_status() AS launch_status, xera_launch_reconcile() AS reconcile;
