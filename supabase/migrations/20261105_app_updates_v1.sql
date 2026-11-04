-- ============================================================
-- App "Updates" channel (phase 1): admin-agent announcements, read-only for everyone else
-- ============================================================
-- Additive only. Safe to re-run.
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> paste -> Run. Then run the checks at the bottom.
--
-- SECURITY MODEL
--   * Posting, editing and deleting only happen through the backend (service_role), which checks the
--     admin token AND a live admin_agents.is_active row on every call. There are no anon/authenticated
--     grants or policies on the table, so the browser can never write to it directly.
--   * Reading goes through the backend too (GET /api/updates), so the table stays closed.
--   * Images live in a PUBLIC-READ bucket ('app-updates'). Public read is what lets <img> tags and the
--     download link work. NO storage policies are created, so anon/authenticated users cannot upload,
--     overwrite or delete; only the backend (service_role) can.
--   * Only JPEG/PNG/WebP, max 2 MB each (SVG is refused: it can carry scripts).
-- ============================================================

CREATE TABLE IF NOT EXISTS app_updates (
    id          BIGSERIAL PRIMARY KEY,
    author_id   BIGINT NOT NULL REFERENCES users(id),
    body        TEXT NOT NULL DEFAULT '' CHECK (char_length(body) <= 4000),
    -- [{"path": "2026/11/abc.jpg", "width": 1200, "height": 800}, ...]  (max 4, enforced by the backend)
    images      JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    edited_at   TIMESTAMPTZ,
    CONSTRAINT app_updates_has_content CHECK (char_length(btrim(body)) > 0 OR jsonb_array_length(images) > 0)
);
CREATE INDEX IF NOT EXISTS idx_app_updates_created ON app_updates (id DESC);

ALTER TABLE app_updates ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app_updates FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON app_updates TO service_role;
GRANT USAGE, SELECT ON SEQUENCE app_updates_id_seq TO service_role;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('app-updates', 'app-updates', true, 2097152, ARRAY['image/jpeg', 'image/png', 'image/webp'])
ON CONFLICT (id) DO UPDATE
    SET public = true, file_size_limit = 2097152, allowed_mime_types = ARRAY['image/jpeg', 'image/png', 'image/webp'];

-- CHECKS (run after):
--   select id, public, file_size_limit from storage.buckets where id = 'app-updates';       -- public = true
--   select policyname from pg_policies where schemaname = 'storage' and policyname ilike '%app-updates%';  -- expect none
--   select tablename, rowsecurity from pg_tables where tablename = 'app_updates';            -- rowsecurity = true
--   select grantee, privilege_type from information_schema.role_table_grants
--     where table_name = 'app_updates';                                                       -- service_role only
