-- ============================================================
-- XERA: manual KYC with ID photos + selfie, reviewed by an admin, DELETED after the decision
-- ============================================================
-- Additive only. Safe to re-run. RUN AFTER 20261027_xera_kyc_provider_v1.sql (and 20261024_...).
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> paste -> Run. Then run the checks at the bottom.
--
-- SECURITY MODEL
--   * The images live in a PRIVATE storage bucket ('xera-kyc'). No policies are created, so anon/authenticated users
--     cannot read or list it at all; only the backend (service_role) can. There are no public or signed links:
--     admins see an image only through the backend, which logs every view.
--   * xera_kyc_documents holds file METADATA only (no image data). Rows are kept after deletion as a record that a file
--     existed and when/why it was erased (storage_path stays, deleted_at is set).
--   * xera_kyc_access_log is the permanent who-looked-at-what record (admin id, document, time). It contains no
--     personal data beyond ids. Never delete it.
--   * The user's consent (time + notice version) is stored on xera_kyc.
-- ============================================================

ALTER TABLE xera_kyc
    ADD COLUMN IF NOT EXISTS docs_consent_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS docs_consent_version TEXT;

CREATE TABLE IF NOT EXISTS xera_kyc_documents (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    kind            TEXT NOT NULL CHECK (kind IN ('id_front', 'id_back', 'selfie')),
    storage_path    TEXT NOT NULL UNIQUE,
    content_type    TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL CHECK (size_bytes > 0),
    sha256          TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    deleted_reason  TEXT                       -- VERIFIED | FAILED | RESUBMITTED | EXPIRED
);
CREATE INDEX IF NOT EXISTS idx_xera_kyc_documents_user ON xera_kyc_documents (user_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS xera_kyc_access_log (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id),     -- whose documents
    admin_id     BIGINT NOT NULL,                          -- who looked
    document_id  BIGINT NOT NULL REFERENCES xera_kyc_documents(id),
    action       TEXT NOT NULL DEFAULT 'view',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_xera_kyc_access_log_user ON xera_kyc_access_log (user_id, admin_id);

ALTER TABLE xera_kyc_documents  ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_kyc_access_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON xera_kyc_documents, xera_kyc_access_log FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON xera_kyc_documents TO service_role;
GRANT SELECT, INSERT ON xera_kyc_access_log TO service_role;          -- append-only for the app: no UPDATE/DELETE
GRANT USAGE, SELECT ON SEQUENCE xera_kyc_documents_id_seq, xera_kyc_access_log_id_seq TO service_role;

-- Private bucket. public = false and NO policies: nobody but service_role can touch it.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('xera-kyc', 'xera-kyc', false, 5242880, ARRAY['image/jpeg'])
ON CONFLICT (id) DO UPDATE SET public = false;

-- CHECKS (run after):
--   select id, public from storage.buckets where id = 'xera-kyc';                      -- public must be false
--   select tablename, rowsecurity from pg_tables where tablename in ('xera_kyc_documents','xera_kyc_access_log');
--   select policyname from pg_policies where schemaname = 'storage' and policyname ilike '%kyc%';   -- expect none
