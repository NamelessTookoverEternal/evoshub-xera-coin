-- ============================================================
-- XERA: KYC status, first-transfer processing fee status, notifications
-- ============================================================
-- Additive only: three new tables, nothing existing is altered, dropped,
-- reset or backfilled. Safe to run on production. Re-runnable (IF NOT EXISTS).
--
-- HOW TO RUN (manual): Supabase dashboard -> SQL Editor -> paste this file ->
-- Run. Then confirm with the three SELECTs at the bottom.
--
-- SECURITY MODEL
--   * Every table has RLS ON and ALL privileges revoked from anon/authenticated.
--     Only the backend (service_role key, server-side only) can read or write.
--     A browser can never set its own KYC status to VERIFIED or its fee to PAID.
--   * VERIFIED / PAID are only ever written by backend code: KYC by an active
--     admin review (or a future provider callback), fee by a server-verified
--     payment webhook. Neither is accepted from a request body.
--   * No identity-document images are stored. The manual-review record keeps
--     only: legal name, country, ID type and the LAST 4 characters of the ID.
-- ============================================================

-- ------------------------------------------------------------
-- 1. KYC
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_kyc (
    user_id        BIGINT PRIMARY KEY REFERENCES users(id),
    status         TEXT NOT NULL DEFAULT 'UNVERIFIED'
                   CHECK (status IN ('UNVERIFIED','PENDING','VERIFIED','FAILED','INFO_REQUIRED')),
    method         TEXT NOT NULL DEFAULT 'MANUAL' CHECK (method IN ('MANUAL','PROVIDER')),
    provider       TEXT,                 -- set only when a real provider is wired in
    provider_ref   TEXT,                 -- the provider's own reference for this check
    legal_name     TEXT,
    country        TEXT,
    id_type        TEXT,
    id_last4       TEXT,
    submitted_at   TIMESTAMPTZ,
    reviewed_at    TIMESTAMPTZ,
    reviewed_by    BIGINT REFERENCES users(id),
    review_note    TEXT,                 -- shown to the user when FAILED / INFO_REQUIRED
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- VERIFIED can never exist without a reviewer or a provider reference.
    CONSTRAINT xera_kyc_verified_has_authority
        CHECK (status <> 'VERIFIED' OR reviewed_by IS NOT NULL OR provider_ref IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_xera_kyc_status ON xera_kyc(status, submitted_at);

-- ------------------------------------------------------------
-- 2. One-time first-transfer processing fee
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_transfer_fee (
    user_id            BIGINT PRIMARY KEY REFERENCES users(id),     -- one fee per account, ever
    status             TEXT NOT NULL DEFAULT 'UNPAID'
                       CHECK (status IN ('UNPAID','PENDING','PAID','FAILED')),
    amount_minor       INTEGER,            -- amount the provider CONFIRMED, in minor units (cents)
    currency           TEXT,               -- currency the provider CONFIRMED
    provider           TEXT,
    payment_reference  TEXT UNIQUE,        -- unique: one payment can never be applied twice
    paid_at            TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT xera_fee_paid_has_proof
        CHECK (status <> 'PAID' OR (payment_reference IS NOT NULL AND paid_at IS NOT NULL
                                    AND amount_minor IS NOT NULL AND currency IS NOT NULL))
);

-- ------------------------------------------------------------
-- 3. Persistent notifications (server-written only)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_notifications (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    kind        TEXT NOT NULL,             -- e.g. kyc_verified, kyc_failed, kyc_info_required
    title       TEXT NOT NULL,
    body        TEXT,
    dedupe_key  TEXT,                      -- same event can never create two notifications
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at     TIMESTAMPTZ,
    CONSTRAINT xera_notifications_dedupe UNIQUE (user_id, dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_xera_notifications_user ON xera_notifications(user_id, created_at DESC);

-- ------------------------------------------------------------
-- 4. Lock-down: service_role only
-- ------------------------------------------------------------
ALTER TABLE xera_kyc            ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_transfer_fee   ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_notifications  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON xera_kyc, xera_transfer_fee, xera_notifications FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON xera_kyc, xera_transfer_fee, xera_notifications TO service_role;
GRANT USAGE, SELECT ON SEQUENCE xera_notifications_id_seq TO service_role;

-- ------------------------------------------------------------
-- Verify (all three should return 0 rows on a fresh run, and rowsecurity = t):
--   SELECT count(*) FROM xera_kyc;
--   SELECT count(*) FROM xera_transfer_fee;
--   SELECT count(*) FROM xera_notifications;
--   SELECT tablename, rowsecurity FROM pg_tables
--    WHERE tablename IN ('xera_kyc','xera_transfer_fee','xera_notifications');
-- ------------------------------------------------------------
