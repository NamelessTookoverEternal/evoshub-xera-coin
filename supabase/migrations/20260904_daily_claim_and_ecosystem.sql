-- ============================================================
-- XERA V1.1 — DAILY CLAIM + ECOSYSTEM DIRECTORY
-- Run in the same shared Supabase project as 20260901_xera_token_v1.sql,
-- after that migration.
--
-- Daily claim is deliberately independent of the 24-hour mining session:
-- it's a once-per-calendar-day bonus (resets at UTC midnight), not a
-- second rolling timer, so a user can mine AND claim daily without the
-- two interfering with each other.
--
-- Ecosystem links is a simple admin-curated directory (name + URL + logo
-- image) shown to users inside the XERA app so they can jump to other
-- Evoxera products. No auth needed to read it (public.users don't get a
-- Supabase Auth session, and the list itself isn't sensitive), but only
-- an active admin_agents member can write to it.
-- ============================================================

-- ------------------------------------------------------------
-- 1. DAILY CLAIM
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_daily_config (
    id              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled         BOOLEAN NOT NULL DEFAULT true,
    reward_amount   NUMERIC(20,4) NOT NULL DEFAULT 5 CHECK (reward_amount > 0),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by      BIGINT REFERENCES users(id)
);
INSERT INTO xera_daily_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS xera_daily_claims (
    user_id         BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    last_claim_date DATE,
    streak          INTEGER NOT NULL DEFAULT 0,
    total_claims    INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Add DAILY_CLAIM to the transaction type allow-list alongside the
-- existing types from the V1 migration.
ALTER TABLE xera_transactions DROP CONSTRAINT IF EXISTS xera_transactions_type_check;
ALTER TABLE xera_transactions ADD CONSTRAINT xera_transactions_type_check CHECK (type IN (
    'MINING_REWARD','XERA_PURCHASE','REFERRAL_REWARD','BONUS','DAILY_CLAIM',
    'ADMIN_CREDIT','ADMIN_DEBIT','REVERSAL','MIGRATION'
));

-- Idempotency backstop, same pattern as the mining-reward index: one
-- DAILY_CLAIM row per user per day, enforced at the DB layer.
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_daily_claim_unique
    ON xera_transactions (reference_id)
    WHERE type = 'DAILY_CLAIM';

-- ---- claim daily reward ---------------------------------------------
-- One Postgres transaction: lock wallet + claim row, verify not already
-- claimed today, credit the ledger, bump the streak. Mirrors
-- xera_claim_mining_reward's shape from the V1 migration.
CREATE OR REPLACE FUNCTION xera_claim_daily_reward(
    p_user_id BIGINT,
    p_reward  NUMERIC
) RETURNS TABLE(new_balance NUMERIC, reward_credited NUMERIC, streak INTEGER)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_wallet    xera_wallets;
    v_claim     xera_daily_claims;
    v_today     DATE := now()::date;
    v_streak    INTEGER;
BEGIN
    SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        INSERT INTO xera_wallets (user_id) VALUES (p_user_id) RETURNING * INTO v_wallet;
    END IF;
    IF v_wallet.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'wallet_not_active' USING ERRCODE = 'P0001';
    END IF;

    SELECT * INTO v_claim FROM xera_daily_claims WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        INSERT INTO xera_daily_claims (user_id, last_claim_date, streak, total_claims)
        VALUES (p_user_id, NULL, 0, 0) RETURNING * INTO v_claim;
    END IF;

    IF v_claim.last_claim_date = v_today THEN
        RAISE EXCEPTION 'already_claimed_today' USING ERRCODE = 'P0011';
    END IF;

    v_streak := CASE
        WHEN v_claim.last_claim_date = v_today - INTERVAL '1 day' THEN v_claim.streak + 1
        ELSE 1
    END;

    INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
    VALUES (v_wallet.id, p_user_id, 'DAILY_CLAIM', p_reward, 'CREDIT',
            p_user_id::text || ':' || v_today::text,
            jsonb_build_object('streak', v_streak));

    UPDATE xera_wallets
        SET cached_balance = cached_balance + p_reward, updated_at = now()
        WHERE id = v_wallet.id
        RETURNING cached_balance INTO new_balance;

    UPDATE xera_daily_claims
        SET last_claim_date = v_today, streak = v_streak, total_claims = v_claim.total_claims + 1, updated_at = now()
        WHERE user_id = p_user_id;

    reward_credited := p_reward;
    streak := v_streak;
    RETURN NEXT;
END;
$$;

-- ------------------------------------------------------------
-- 2. ECOSYSTEM DIRECTORY
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_ecosystem_links (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    image_url   TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  BIGINT REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_xera_ecosystem_active_sort ON xera_ecosystem_links(is_active, sort_order);
