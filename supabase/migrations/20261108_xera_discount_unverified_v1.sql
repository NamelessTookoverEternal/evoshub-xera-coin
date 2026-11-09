-- ============================================================
-- XERA discount: users who have NOT done KYC can still use it, for more XERA
-- ============================================================
-- Same cash discount (e.g. GHS 0.20 off a GHS 5.00 bundle), but the XERA cost is multiplied:
--   verified:   20 XERA      unverified (multiplier 1.75): 35 XERA
-- unverified_multiplier = 0 puts the old rule back (KYC required).
-- Run AFTER 20261107_xera_data_discount_v1.sql. Safe to re-run. Changes nothing while the discount is off.
-- (The old require_kyc column is no longer used; leave it.)
-- ============================================================
ALTER TABLE xera_discount_config
    ADD COLUMN IF NOT EXISTS unverified_multiplier NUMERIC(6,2) NOT NULL DEFAULT 1.75
    CHECK (unverified_multiplier >= 0 AND unverified_multiplier <= 20);

--   Change it:   UPDATE xera_discount_config SET unverified_multiplier = 1.5 WHERE id = 1;   -- 30 XERA
--   KYC only:    UPDATE xera_discount_config SET unverified_multiplier = 0   WHERE id = 1;
