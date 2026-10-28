-- ============================================================
-- XERA: hybrid KYC (verification provider + admin final decision)
-- ============================================================
-- Additive only: new columns on xera_kyc, one new table, one new constraint. Nothing existing is dropped, reset
-- or rewritten. Safe to run on production and safe to re-run. RUN AFTER 20261024_xera_kyc_fee_readiness_v1.sql.
--
-- HOW TO RUN (manual): Supabase dashboard -> SQL Editor -> paste this file -> Run. Then run the checks at the bottom.
--
-- SECURITY MODEL
--   * ID photos and selfies are NEVER stored by us: the user captures them on the provider's own page. Only the
--     provider's reference and its pass/fail/in-review result are kept here.
--   * A provider can only ever set provider_status. xera_kyc.status = VERIFIED needs an admin (reviewed_by) AND, for
--     provider cases, provider_status = 'APPROVED'. The CHECK below enforces that in the database itself.
--   * RLS on, everything revoked from anon/authenticated; only the backend (service_role) can read or write.
-- ============================================================

ALTER TABLE xera_kyc
    ADD COLUMN IF NOT EXISTS provider_status     TEXT,          -- STARTED | IN_REVIEW | APPROVED | DECLINED | ABANDONED
    ADD COLUMN IF NOT EXISTS provider_attempt   TEXT,          -- OUR per-attempt reference sent to the provider
    ADD COLUMN IF NOT EXISTS provider_reason    TEXT,          -- short machine reason from the provider (no personal data)
    ADD COLUMN IF NOT EXISTS provider_checked_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'xera_kyc_provider_status_valid') THEN
        ALTER TABLE xera_kyc ADD CONSTRAINT xera_kyc_provider_status_valid
            CHECK (provider_status IS NULL OR provider_status IN ('STARTED','IN_REVIEW','APPROVED','DECLINED','ABANDONED'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'xera_kyc_provider_verified_needs_both') THEN
        -- A provider case can be VERIFIED only by an admin AND only after the provider approved it.
        ALTER TABLE xera_kyc ADD CONSTRAINT xera_kyc_provider_verified_needs_both
            CHECK (method <> 'PROVIDER' OR status <> 'VERIFIED' OR (reviewed_by IS NOT NULL AND provider_status = 'APPROVED'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_xera_kyc_provider_ref ON xera_kyc (provider, provider_ref);

-- Callback de-duplication: the same provider event can never be applied twice.
CREATE TABLE IF NOT EXISTS xera_kyc_provider_events (
    provider      TEXT NOT NULL,
    event_id      TEXT NOT NULL,
    user_id       BIGINT REFERENCES users(id),
    provider_ref  TEXT,
    status        TEXT,
    received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, event_id)
);

ALTER TABLE xera_kyc_provider_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON xera_kyc_provider_events FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON xera_kyc_provider_events TO service_role;

-- ------------------------------------------------------------
-- Checks (expect: the 4 new columns, 2 constraints, rowsecurity = t):
--   SELECT column_name FROM information_schema.columns
--    WHERE table_name = 'xera_kyc' AND column_name LIKE 'provider%' ORDER BY 1;
--   SELECT conname FROM pg_constraint WHERE conname LIKE 'xera_kyc_provider%';
--   SELECT tablename, rowsecurity FROM pg_tables WHERE tablename = 'xera_kyc_provider_events';
-- ------------------------------------------------------------
