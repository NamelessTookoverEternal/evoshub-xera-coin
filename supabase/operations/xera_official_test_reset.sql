-- SUPERSEDED — DO NOT RUN.
-- This earlier script credited 100 XERA to EVERY wallet, did not reset the
-- entitlement ledger (xera_mining_entitlement_state), and kept backups in the
-- public schema. It has been replaced by:
--     operations/xera_official_launch_reset.sql
-- Running this file deliberately fails so it can never be used by mistake.
DO $$
BEGIN
    RAISE EXCEPTION 'xera_official_test_reset.sql is superseded. Use xera_official_launch_reset.sql.';
END $$;
