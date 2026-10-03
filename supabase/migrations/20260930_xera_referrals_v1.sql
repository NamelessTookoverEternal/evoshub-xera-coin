-- ============================================================
-- XERA / EVOS ECOSYSTEM — REFERRALS V1
-- Run in the shared Supabase SQL Editor, after 20260923_xera_hashrate_v1.sql.
--
-- Design: the referral identity lives on the SHARED `users` row, which
-- EVOSGPT, EVOS Data, EVOS Hub and XERA all read:
--
--     users.referral_code   this user's own invite code
--     users.referred_by     the code of whoever invited them (set ONCE)
--
-- EVOSGPT and EVOS Data already write both columns at signup, so a user
-- referred in any product is already attributed in every product. This
-- migration (a) guarantees every user has a code, (b) makes codes unique
-- and case-insensitive, and (c) adds XERA's own tracking/reward layer
-- (xera_referrals) on top of the shared columns.
--
-- First-touch rule: once users.referred_by is set it is never overwritten.
-- ============================================================

-- ------------------------------------------------------------
-- 1. SHARED users COLUMNS (no-ops if EVOSGPT/EVOS Data already added them)
-- ------------------------------------------------------------

ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by   TEXT;

-- EVOS-XXXX-YYYYYY  (same prefix style EVOSGPT uses, 6 hex for fewer collisions)
CREATE OR REPLACE FUNCTION evos_generate_referral_code(p_seed TEXT)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    v_prefix TEXT := upper(left(regexp_replace(coalesce(p_seed, ''), '[^a-zA-Z0-9]', '', 'g'), 4));
    v_code   TEXT;
BEGIN
    IF v_prefix = '' THEN v_prefix := 'USER'; END IF;
    LOOP
        v_code := 'EVOS-' || v_prefix || '-' || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 6));
        EXIT WHEN NOT EXISTS (SELECT 1 FROM users WHERE upper(referral_code) = v_code);
    END LOOP;
    RETURN v_code;
END;
$$;

-- Backfill: every existing user without a code gets one. Existing codes
-- (EVOSGPT's EVOS-XXXX-YYYY, EVOS Data's username_1234) are left untouched
-- so links people have already shared keep working.
UPDATE users
   SET referral_code = evos_generate_referral_code(username)
 WHERE referral_code IS NULL OR btrim(referral_code) = '';

-- Unique + case-insensitive lookups. Wrapped so a pre-existing duplicate
-- (possible with EVOS Data's username_last4 format) warns instead of
-- aborting the whole migration; fix the duplicates and re-run this block.
DO $$
BEGIN
    CREATE UNIQUE INDEX IF NOT EXISTS users_referral_code_upper_key
        ON users (upper(referral_code)) WHERE referral_code IS NOT NULL;
EXCEPTION WHEN unique_violation THEN
    RAISE WARNING 'Duplicate users.referral_code values exist — unique index NOT created. Find them with: SELECT upper(referral_code), count(*) FROM users GROUP BY 1 HAVING count(*) > 1;';
END $$;

CREATE INDEX IF NOT EXISTS users_referred_by_idx ON users (upper(referred_by)) WHERE referred_by IS NOT NULL;

-- ------------------------------------------------------------
-- 2. XERA REFERRAL TRACKING (extends the table from the V1 migration)
-- ------------------------------------------------------------

ALTER TABLE xera_referrals ADD COLUMN IF NOT EXISTS referral_code_used TEXT;
ALTER TABLE xera_referrals ADD COLUMN IF NOT EXISTS source_product     TEXT NOT NULL DEFAULT 'xera';
ALTER TABLE xera_referrals ADD COLUMN IF NOT EXISTS qualified_at       TIMESTAMPTZ;
ALTER TABLE xera_referrals ADD COLUMN IF NOT EXISTS rewarded_at        TIMESTAMPTZ;

-- A person can only ever be referred once, by one person.
CREATE UNIQUE INDEX IF NOT EXISTS xera_referrals_referred_unique ON xera_referrals (referred_user_id);
CREATE INDEX IF NOT EXISTS xera_referrals_referrer_idx ON xera_referrals (referrer_user_id, created_at DESC);

DO $$
BEGIN
    ALTER TABLE xera_referrals ADD CONSTRAINT xera_referrals_no_self CHECK (referrer_user_id <> referred_user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Reward amounts. BOTH DEFAULT TO 0: referrals are tracked from day one but
-- nothing is minted until you set amounts here AND flip
-- xera_config.referral_enabled to true.
CREATE TABLE IF NOT EXISTS xera_referral_config (
    id               SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    referrer_reward  NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK (referrer_reward >= 0),
    referee_reward   NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK (referee_reward  >= 0),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by       BIGINT REFERENCES users(id)
);
INSERT INTO xera_referral_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- One REFERRAL_REWARD row per (referral, side) — idempotency backstop.
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_referral_reward_unique
    ON xera_transactions (reference_id)
    WHERE type = 'REFERRAL_REWARD';

-- Exact, case-insensitive code lookup (no LIKE wildcards: EVOS Data codes
-- contain "_"). Returns only what is needed to greet an invitee.
CREATE OR REPLACE FUNCTION xera_resolve_referral_code(p_code TEXT)
RETURNS TABLE(id BIGINT, username TEXT, full_name TEXT, referral_code TEXT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT u.id, u.username::text, u.full_name::text, u.referral_code::text
      FROM users u
     WHERE upper(u.referral_code) = upper(btrim(p_code))
     LIMIT 1;
$$;

-- ------------------------------------------------------------
-- 3. LINK A USER TO THEIR REFERRER
--    Called at XERA signup with the code from the invite link, and again
--    (code NULL) when a user from another product first opens XERA, so
--    EVOSGPT / EVOS Data referrals show up in XERA too.
--    Returns the referrer's user id, or NULL if there is nothing to link.
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION xera_link_referral(
    p_user_id BIGINT,
    p_code    TEXT DEFAULT NULL,
    p_source  TEXT DEFAULT 'xera'
) RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_user          users;
    v_code          TEXT;
    v_referrer_id   BIGINT;
    v_referrer_code TEXT;
BEGIN
    SELECT * INTO v_user FROM users WHERE id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RETURN NULL; END IF;

    -- First touch wins: an existing referred_by always beats a new code.
    v_code := NULLIF(btrim(COALESCE(v_user.referred_by, p_code, '')), '');
    IF v_code IS NULL THEN RETURN NULL; END IF;

    SELECT id, referral_code INTO v_referrer_id, v_referrer_code
      FROM users
     WHERE upper(referral_code) = upper(v_code) AND id <> p_user_id
     LIMIT 1;
    IF v_referrer_id IS NULL THEN RETURN NULL; END IF;  -- unknown code / self-referral

    IF v_user.referred_by IS NULL OR btrim(v_user.referred_by) = '' THEN
        UPDATE users SET referred_by = v_referrer_code WHERE id = p_user_id;
    END IF;

    INSERT INTO xera_referrals (referrer_user_id, referred_user_id, referral_code_used, source_product)
    VALUES (v_referrer_id, p_user_id, v_referrer_code, COALESCE(NULLIF(p_source, ''), 'xera'))
    ON CONFLICT (referred_user_id) DO NOTHING;

    RETURN v_referrer_id;
END;
$$;

-- ------------------------------------------------------------
-- 4. QUALIFY + REWARD
--    A referral "qualifies" on the referred user's first completed mining
--    claim (stops throwaway signups from earning anything). Idempotent:
--    safe to call after every claim.
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION xera_qualify_referral(p_referred_user_id BIGINT)
RETURNS TABLE(qualified BOOLEAN, referrer_paid NUMERIC, referee_paid NUMERIC)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_ref      xera_referrals;
    v_cfg      xera_referral_config;
    v_enabled  BOOLEAN;
    v_wallet   xera_wallets;
BEGIN
    qualified := false; referrer_paid := 0; referee_paid := 0;

    SELECT * INTO v_ref FROM xera_referrals
     WHERE referred_user_id = p_referred_user_id FOR UPDATE;
    IF NOT FOUND OR v_ref.qualified_at IS NOT NULL THEN RETURN NEXT; RETURN; END IF;

    UPDATE xera_referrals SET qualified_at = now(), status = 'qualified' WHERE id = v_ref.id;
    qualified := true;

    SELECT referral_enabled INTO v_enabled FROM xera_config WHERE id = 1;
    SELECT * INTO v_cfg FROM xera_referral_config WHERE id = 1;
    IF NOT COALESCE(v_enabled, false) OR (v_cfg.referrer_reward = 0 AND v_cfg.referee_reward = 0) THEN
        RETURN NEXT; RETURN;
    END IF;

    -- Referrer side
    IF v_cfg.referrer_reward > 0 THEN
        SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = v_ref.referrer_user_id FOR UPDATE;
        IF NOT FOUND THEN
            INSERT INTO xera_wallets (user_id) VALUES (v_ref.referrer_user_id) RETURNING * INTO v_wallet;
        END IF;
        IF v_wallet.status = 'ACTIVE' THEN
            INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
            VALUES (v_wallet.id, v_ref.referrer_user_id, 'REFERRAL_REWARD', v_cfg.referrer_reward, 'CREDIT',
                    'ref:' || v_ref.id || ':referrer',
                    jsonb_build_object('referral_id', v_ref.id, 'referred_user_id', p_referred_user_id, 'side', 'referrer'));
            UPDATE xera_wallets SET cached_balance = cached_balance + v_cfg.referrer_reward, updated_at = now()
             WHERE id = v_wallet.id;
            referrer_paid := v_cfg.referrer_reward;
        END IF;
    END IF;

    -- Referee side
    IF v_cfg.referee_reward > 0 THEN
        SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = p_referred_user_id FOR UPDATE;
        IF NOT FOUND THEN
            INSERT INTO xera_wallets (user_id) VALUES (p_referred_user_id) RETURNING * INTO v_wallet;
        END IF;
        IF v_wallet.status = 'ACTIVE' THEN
            INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
            VALUES (v_wallet.id, p_referred_user_id, 'REFERRAL_REWARD', v_cfg.referee_reward, 'CREDIT',
                    'ref:' || v_ref.id || ':referee',
                    jsonb_build_object('referral_id', v_ref.id, 'referrer_user_id', v_ref.referrer_user_id, 'side', 'referee'));
            UPDATE xera_wallets SET cached_balance = cached_balance + v_cfg.referee_reward, updated_at = now()
             WHERE id = v_wallet.id;
            referee_paid := v_cfg.referee_reward;
        END IF;
    END IF;

    IF referrer_paid > 0 OR referee_paid > 0 THEN
        UPDATE xera_referrals
           SET rewarded_at = now(), reward_amount = referrer_paid, status = 'rewarded'
         WHERE id = v_ref.id;
    END IF;

    RETURN NEXT;
END;
$$;

-- Backend-only: these use the service_role key. Never callable from the browser.
REVOKE ALL ON FUNCTION xera_link_referral(BIGINT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION xera_qualify_referral(BIGINT)          FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION xera_resolve_referral_code(TEXT)       FROM PUBLIC, anon, authenticated;
