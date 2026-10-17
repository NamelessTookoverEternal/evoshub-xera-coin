-- EVOSGPT: Supabase-first memory, reviewed shared knowledge, usage metrics.
-- Idempotent and additive. Existing tables (users, evosgpt_memory, evosgpt_long_memory, ...) are reused;
-- nothing is dropped or rewritten. Run in the shared Hub / EVOS Data Supabase project (SQL editor).
--
-- Three kinds of data stay separate:
--   A. conversation history  -> evosgpt_memory        (private, per user)
--   B. personal memory       -> evosgpt_long_memory   (private, per user)
--   C. shared knowledge      -> evosgpt_knowledge     (NO user_id; only status='approved' is ever served)

-- A. history: optional conversation grouping + faster per-user recency scans
ALTER TABLE evosgpt_memory ADD COLUMN IF NOT EXISTS conversation_id TEXT;
CREATE INDEX IF NOT EXISTS idx_evosgpt_memory_user_created ON evosgpt_memory(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evosgpt_memory_conversation ON evosgpt_memory(user_id, conversation_id);

-- C. shared knowledge (sanitised; AI-generated rows start as 'pending' and need human review)
CREATE TABLE IF NOT EXISTS evosgpt_knowledge (
    id             BIGSERIAL PRIMARY KEY,
    question_key   TEXT NOT NULL UNIQUE,            -- normalised content words, for exact matches
    question       TEXT NOT NULL,
    answer         TEXT NOT NULL,
    source         TEXT NOT NULL DEFAULT 'ai_generated' CHECK (source IN ('admin_verified', 'ai_generated')),
    status         TEXT NOT NULL DEFAULT 'pending'      CHECK (status IN ('pending', 'approved', 'rejected')),
    confidence     REAL NOT NULL DEFAULT 0.5,       -- reviewer may raise it; the app requires >= 0.7 to serve
    seen_count     INTEGER NOT NULL DEFAULT 1,      -- times the question was asked
    use_count      INTEGER NOT NULL DEFAULT 0,      -- times the stored answer was served
    conflict_count INTEGER NOT NULL DEFAULT 0,      -- new answers that disagreed with this approved one
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at    TIMESTAMPTZ,
    expires_at     TIMESTAMPTZ                      -- NULL = no expiry; set one for anything that can go stale
);
CREATE INDEX IF NOT EXISTS idx_evosgpt_knowledge_status ON evosgpt_knowledge(status, seen_count DESC);

-- Usage metrics: which path answered each chat, and OpenAI token usage where known
CREATE TABLE IF NOT EXISTS evosgpt_usage_events (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT REFERENCES users(id) ON DELETE CASCADE,
    route             TEXT NOT NULL CHECK (route IN ('native', 'history', 'knowledge', 'openai')),
    purpose           TEXT NOT NULL DEFAULT 'chat' CHECK (purpose IN ('chat', 'memory_maintenance')),
    model             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    est_cost_usd      NUMERIC(12, 6),               -- estimate from token counts; excludes database/hosting costs
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_evosgpt_usage_user_created ON evosgpt_usage_events(user_id, created_at DESC);

-- Operator view: how many chats avoided OpenAI, per day (no message content, no user ids)
CREATE OR REPLACE VIEW evosgpt_usage_daily AS
SELECT date_trunc('day', created_at)::date AS day,
       count(*) FILTER (WHERE purpose = 'chat')                                   AS chats,
       count(*) FILTER (WHERE purpose = 'chat' AND route = 'native')              AS native,
       count(*) FILTER (WHERE purpose = 'chat' AND route = 'history')             AS history,
       count(*) FILTER (WHERE purpose = 'chat' AND route = 'knowledge')           AS knowledge,
       count(*) FILTER (WHERE purpose = 'chat' AND route = 'openai')              AS openai_text,
       count(*) FILTER (WHERE purpose = 'memory_maintenance')                     AS memory_maintenance_calls,
       coalesce(sum(prompt_tokens), 0)                                            AS prompt_tokens,
       coalesce(sum(completion_tokens), 0)                                        AS completion_tokens,
       coalesce(sum(est_cost_usd), 0)                                             AS est_cost_usd
FROM evosgpt_usage_events
GROUP BY 1
ORDER BY 1 DESC;

-- Lock the new tables to the backend's service-role key. RLS on with no policies = anon/authenticated
-- clients get nothing (the service role bypasses RLS). Shared knowledge must never be directly readable.
ALTER TABLE evosgpt_knowledge     ENABLE ROW LEVEL SECURITY;
ALTER TABLE evosgpt_usage_events  ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON evosgpt_knowledge, evosgpt_usage_events FROM anon, authenticated;
REVOKE ALL ON evosgpt_usage_daily FROM anon, authenticated;

-- ------------------------------------------------------------------------------------------------
-- Reviewing AI-generated candidates (run by an operator in the SQL editor):
--   SELECT id, question, answer, seen_count FROM evosgpt_knowledge WHERE status = 'pending' ORDER BY seen_count DESC;
--   -- approve (and set an expiry if the answer can go stale):
--   UPDATE evosgpt_knowledge SET status='approved', confidence=0.9, reviewed_at=NOW(),
--          expires_at = NOW() + INTERVAL '180 days' WHERE id = <id>;
--   -- reject:
--   UPDATE evosgpt_knowledge SET status='rejected', reviewed_at=NOW() WHERE id = <id>;
--   -- add a verified answer yourself:
--   INSERT INTO evosgpt_knowledge (question_key, question, answer, source, status, confidence, reviewed_at)
--   VALUES ('<sorted lowercase content words>', '<question>', '<answer>', 'admin_verified', 'approved', 1.0, NOW());
--   (question_key = the question's content words, lowercased, de-duplicated, sorted and space-joined;
--    the app also matches by similarity, so an approximate key is fine.)
--
-- Privacy controls:
--   * DELETE /api/evosgpt/memory/{user_id} (existing) deletes that user's history and personal memory.
--   * evosgpt_knowledge has no user_id and only holds text the privacy filter left unchanged, so there is
--     nothing per-user to export or delete there; reject or delete a row by id if it is ever reported.
--   * Retention: rows in evosgpt_memory older than EVOSGPT_RETENTION_DAYS (default 365) or beyond
--     EVOSGPT_RETENTION_MAX_ROWS per user (default 5000) are pruned in the background.
