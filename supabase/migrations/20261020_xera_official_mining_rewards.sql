-- XERA official mining phase: reward schedule and daily claim reward.
-- Base mining reward tiers are implemented in python/xera/mining.py.
-- This migration updates the existing daily-claim singleton to 2 XERA.
INSERT INTO xera_daily_config (id, reward_amount, updated_at)
VALUES (1, 2, now())
ON CONFLICT (id) DO UPDATE
SET reward_amount = EXCLUDED.reward_amount,
    updated_at = now();
