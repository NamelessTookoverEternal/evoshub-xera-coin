-- REFERENCE ONLY: these tables already exist in production (shared Supabase project with the Hub / EVOS Data).
-- Idempotent, so safe to run again on a fresh project. No migration is needed for the Hub merge.
-- ============================================================
-- EVOSGPT TABLES — Run in EVOSDATA Supabase SQL Editor
-- The shared `users` table already exists in EVOSDATA.
-- We add evosgpt_tier to it and create evosgpt_* tables.
-- ============================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS evosgpt_tier TEXT DEFAULT 'Basic';

CREATE TABLE IF NOT EXISTS evosgpt_memory (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT REFERENCES users(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evosgpt_long_memory (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    summary    TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evosgpt_daily_chats (
    id      BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    date    DATE NOT NULL,
    count   INTEGER DEFAULT 0,
    UNIQUE(user_id, date)
);

CREATE TABLE IF NOT EXISTS evosgpt_purchases (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT REFERENCES users(id) ON DELETE CASCADE,
    tier       TEXT NOT NULL,
    reference  TEXT UNIQUE NOT NULL,
    status     TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evosgpt_coupons (
    id         BIGSERIAL PRIMARY KEY,
    code       TEXT UNIQUE NOT NULL,
    tier       TEXT NOT NULL,
    used       BOOLEAN DEFAULT FALSE,
    used_by    BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evosgpt_memory_user     ON evosgpt_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_evosgpt_memory_created  ON evosgpt_memory(created_at);
CREATE INDEX IF NOT EXISTS idx_evosgpt_daily_user_date ON evosgpt_daily_chats(user_id, date);
CREATE INDEX IF NOT EXISTS idx_evosgpt_purchases_ref   ON evosgpt_purchases(reference);
CREATE INDEX IF NOT EXISTS idx_evosgpt_purchases_user  ON evosgpt_purchases(user_id);

INSERT INTO evosgpt_coupons (code, tier) VALUES
    ('EVOSPRO2026',  'Pro'),
    ('EVOSCORE2026', 'Core'),
    ('EVOSFOUND',    'Founder')
ON CONFLICT (code) DO NOTHING;

-- ============================================================
-- IMAGE GENERATION — Supabase Storage
-- ============================================================
-- The backend auto-creates a public bucket called "evosgpt-images" on
-- startup (see ensure_image_bucket() in main.py), so you normally don't
-- need to do anything here. If your service-role key doesn't have
-- permission to create buckets, create it manually instead:
--   Supabase Dashboard -> Storage -> New bucket -> name: evosgpt-images
--   -> toggle "Public bucket" ON -> Save.
-- No SQL is required for this — Storage buckets aren't SQL tables.
