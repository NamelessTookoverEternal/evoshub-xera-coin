-- ============================================================
-- XERA Token (Coin) V1 — MINING WALLET SCHEMA
-- Run in the shared Supabase SQL Editor used by EVOS Hub (same project as the
-- shared `users` table — see evosgpt_rebirth/backend/schema.sql
-- for precedent: new products add their own xera_* tables here
-- rather than standing up a separate database).
--
-- Isolation guarantee: nothing in this file touches, references,
-- or writes to agent_wallets / agent_transactions / orders. XERA
-- accounting is fully independent of the EVOS Data Services
-- agent fiat wallet, per explicit instruction.
-- ============================================================

-- ------------------------------------------------------------
-- 1. CONFIGURATION (singleton rows, id = 1)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_config (
    id                  SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    system_enabled      BOOLEAN NOT NULL DEFAULT true,
    current_phase       TEXT NOT NULL DEFAULT 'MINING',
    mining_enabled      BOOLEAN NOT NULL DEFAULT true,
    sale_enabled        BOOLEAN NOT NULL DEFAULT false,
    withdrawal_enabled  BOOLEAN NOT NULL DEFAULT false,
    transfer_enabled    BOOLEAN NOT NULL DEFAULT false,
    referral_enabled    BOOLEAN NOT NULL DEFAULT false,
    onchain_enabled     BOOLEAN NOT NULL DEFAULT false,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by          BIGINT REFERENCES users(id)
);
INSERT INTO xera_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS xera_allocations (
    id                      SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    total_target            NUMERIC(20,4) NOT NULL DEFAULT 500000000,
    mining_allocation       NUMERIC(20,4) NOT NULL DEFAULT 75000000,
    sale_allocation         NUMERIC(20,4) NOT NULL DEFAULT 125000000,
    community_allocation    NUMERIC(20,4) NOT NULL DEFAULT 25000000,
    liquidity_allocation    NUMERIC(20,4) NOT NULL DEFAULT 75000000,
    treasury_allocation     NUMERIC(20,4) NOT NULL DEFAULT 200000000,
    mining_distributed      NUMERIC(20,4) NOT NULL DEFAULT 0,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by              BIGINT REFERENCES users(id),
    CONSTRAINT xera_allocations_sum_within_target CHECK (
        mining_allocation + sale_allocation + community_allocation
        + liquidity_allocation + treasury_allocation <= total_target
    ),
    CONSTRAINT xera_mining_distributed_within_allocation CHECK (
        mining_distributed <= mining_allocation
    ),
    CONSTRAINT xera_mining_distributed_non_negative CHECK (mining_distributed >= 0)
);
INSERT INTO xera_allocations (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS xera_mining_config (
    id                      SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    session_hours           INTEGER NOT NULL DEFAULT 24,
    mining_start            DATE,
    mining_end              DATE,
    min_reward_per_session  NUMERIC(20,4) NOT NULL DEFAULT 1,
    max_reward_per_session  NUMERIC(20,4) NOT NULL DEFAULT 5000,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by              BIGINT REFERENCES users(id),
    CONSTRAINT xera_mining_reward_bounds_valid CHECK (min_reward_per_session <= max_reward_per_session)
);
INSERT INTO xera_mining_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Present but inert in V1 — every write path is blocked in application
-- code while xera_config.sale_enabled = false (see app/xera/routes.py).
CREATE TABLE IF NOT EXISTS xera_sale_config (
    id                  SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    sale_enabled        BOOLEAN NOT NULL DEFAULT false,
    price_ghs           NUMERIC(10,4) NOT NULL DEFAULT 0.01,
    currency            TEXT NOT NULL DEFAULT 'GHS',
    minimum_purchase    NUMERIC(20,4) NOT NULL DEFAULT 1000,
    maximum_purchase    NUMERIC(20,4) NOT NULL DEFAULT 1000000,
    sale_start           TIMESTAMPTZ,
    sale_end             TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by           BIGINT REFERENCES users(id)
);
INSERT INTO xera_sale_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ------------------------------------------------------------
-- 2. WALLET + LEDGER
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_wallets (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    cached_balance  NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK (cached_balance >= 0),
    status          TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUSPENDED','FLAGGED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS xera_transactions (
    id              BIGSERIAL PRIMARY KEY,
    wallet_id       BIGINT NOT NULL REFERENCES xera_wallets(id),
    user_id         BIGINT NOT NULL REFERENCES users(id),
    type            TEXT NOT NULL CHECK (type IN (
                        'MINING_REWARD','XERA_PURCHASE','REFERRAL_REWARD','BONUS',
                        'ADMIN_CREDIT','ADMIN_DEBIT','REVERSAL','MIGRATION'
                    )),
    amount          NUMERIC(20,4) NOT NULL CHECK (amount > 0),
    direction       TEXT NOT NULL CHECK (direction IN ('CREDIT','DEBIT')),
    status          TEXT NOT NULL DEFAULT 'CONFIRMED' CHECK (status IN ('PENDING','CONFIRMED','REVERSED')),
    reference_id    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at    TIMESTAMPTZ DEFAULT now(),
    metadata        JSONB DEFAULT '{}'::jsonb
);

-- Idempotency backstop: even if application logic somehow called the claim
-- path twice for the same session, the DB itself refuses a second
-- MINING_REWARD row with the same reference_id (session id).
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_mining_reward_unique
    ON xera_transactions (reference_id)
    WHERE type = 'MINING_REWARD';

CREATE INDEX IF NOT EXISTS idx_xera_tx_user   ON xera_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_xera_tx_wallet ON xera_transactions(wallet_id);
CREATE INDEX IF NOT EXISTS idx_xera_tx_type   ON xera_transactions(type);

-- ------------------------------------------------------------
-- 3. MINING SESSIONS
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_mining_sessions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL,
    rate_snapshot       NUMERIC(20,4) NOT NULL,
    estimated_reward    NUMERIC(20,4) NOT NULL,
    status              TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN
                            ('ACTIVE','COMPLETED','CLAIMED','CANCELLED','FLAGGED')),
    claimed_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- DB-level enforcement of "one active session per user" — a partial unique
-- index, not just an application check, so a race between two concurrent
-- "start mining" requests is rejected by Postgres itself.
CREATE UNIQUE INDEX IF NOT EXISTS xera_one_active_session_per_user
    ON xera_mining_sessions(user_id)
    WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_xera_mining_user   ON xera_mining_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_xera_mining_status ON xera_mining_sessions(status);

-- ------------------------------------------------------------
-- 4. FUTURE-PHASE TABLES — schema exists, all writes blocked in
--    application code by xera_config feature flags. No route in
--    V1 inserts into these.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_purchases (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    xera_amount      NUMERIC(20,4) NOT NULL,
    price_ghs       NUMERIC(20,4) NOT NULL,
    paystack_ref    TEXT UNIQUE,
    status          TEXT NOT NULL DEFAULT 'pending_payment',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS xera_withdrawals (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    xera_amount      NUMERIC(20,4) NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS xera_referrals (
    id                  BIGSERIAL PRIMARY KEY,
    referrer_user_id    BIGINT NOT NULL REFERENCES users(id),
    referred_user_id    BIGINT NOT NULL REFERENCES users(id),
    reward_amount       NUMERIC(20,4) DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (referrer_user_id, referred_user_id)
);

-- ------------------------------------------------------------
-- 5. AUDIT / SECURITY
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_admin_actions (
    id          BIGSERIAL PRIMARY KEY,
    admin_id    BIGINT NOT NULL REFERENCES users(id),
    action      TEXT NOT NULL,
    old_value   JSONB,
    new_value   JSONB,
    reason      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS xera_security_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT REFERENCES users(id),
    event_type  TEXT NOT NULL,
    details     JSONB DEFAULT '{}'::jsonb,
    ip_address  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_xera_security_user ON xera_security_events(user_id);
CREATE INDEX IF NOT EXISTS idx_xera_security_type ON xera_security_events(event_type);

-- ============================================================
-- 6. ATOMIC OPERATIONS (SECURITY DEFINER plpgsql functions)
--
-- These exist because the Supabase Python client cannot express
-- "lock this row, check several conditions, write to three
-- tables, commit or roll back all of it together" as a single
-- request — doing that as separate .execute() calls from Python
-- would leave a window for a second concurrent request to slip
-- through between them. Each function below runs as ONE Postgres
-- transaction, so the race conditions section 9/27 of the brief
-- worry about are closed at the database layer, not just checked
-- for in application code.
-- ============================================================

-- ---- start mining -------------------------------------------------
CREATE OR REPLACE FUNCTION xera_start_mining_session(
    p_user_id   BIGINT,
    p_rate      NUMERIC,
    p_hours     INTEGER,
    p_max_reward NUMERIC
) RETURNS xera_mining_sessions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_wallet    xera_wallets;
    v_session   xera_mining_sessions;
    v_reward    NUMERIC(20,4);
BEGIN
    -- Ensure a wallet exists and lock it (also catches SUSPENDED users).
    SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        INSERT INTO xera_wallets (user_id) VALUES (p_user_id) RETURNING * INTO v_wallet;
    END IF;

    IF v_wallet.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'wallet_not_active' USING ERRCODE = 'P0001';
    END IF;

    v_reward := LEAST(GREATEST(p_rate, 0), p_max_reward);

    BEGIN
        INSERT INTO xera_mining_sessions (user_id, expires_at, rate_snapshot, estimated_reward)
        VALUES (p_user_id, now() + make_interval(hours => p_hours), p_rate, v_reward)
        RETURNING * INTO v_session;
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'active_session_exists' USING ERRCODE = 'P0002';
    END;

    RETURN v_session;
END;
$$;

-- ---- claim mining reward -------------------------------------------
CREATE OR REPLACE FUNCTION xera_claim_mining_reward(
    p_session_id BIGINT,
    p_user_id    BIGINT
) RETURNS TABLE(new_balance NUMERIC, reward_credited NUMERIC)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_session   xera_mining_sessions;
    v_alloc     xera_allocations;
    v_wallet    xera_wallets;
    v_reward    NUMERIC(20,4);
    v_remaining NUMERIC(20,4);
BEGIN
    SELECT * INTO v_session
        FROM xera_mining_sessions
        WHERE id = p_session_id AND user_id = p_user_id
        FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'session_not_found' USING ERRCODE = 'P0003';
    END IF;

    IF v_session.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'invalid_session_status' USING ERRCODE = 'P0004';
    END IF;

    IF now() < v_session.expires_at THEN
        RAISE EXCEPTION 'not_yet_expired' USING ERRCODE = 'P0005';
    END IF;

    SELECT * INTO v_alloc FROM xera_allocations WHERE id = 1 FOR UPDATE;
    v_remaining := v_alloc.mining_allocation - v_alloc.mining_distributed;

    v_reward := LEAST(v_session.estimated_reward, GREATEST(v_remaining, 0));
    IF v_reward <= 0 THEN
        UPDATE xera_mining_sessions SET status = 'FLAGGED' WHERE id = p_session_id;
        RAISE EXCEPTION 'allocation_exhausted' USING ERRCODE = 'P0006';
    END IF;

    SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet_not_found' USING ERRCODE = 'P0007';
    END IF;
    IF v_wallet.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'wallet_not_active' USING ERRCODE = 'P0001';
    END IF;

    -- Ledger row is authoritative; unique index on (reference_id) WHERE
    -- type='MINING_REWARD' means even a second call for this session id
    -- can never insert a second reward row.
    INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
    VALUES (v_wallet.id, p_user_id, 'MINING_REWARD', v_reward, 'CREDIT', p_session_id::text,
            jsonb_build_object('session_id', p_session_id));

    UPDATE xera_wallets
        SET cached_balance = cached_balance + v_reward, updated_at = now()
        WHERE id = v_wallet.id
        RETURNING cached_balance INTO new_balance;

    UPDATE xera_allocations
        SET mining_distributed = mining_distributed + v_reward, updated_at = now()
        WHERE id = 1;

    UPDATE xera_mining_sessions
        SET status = 'CLAIMED', claimed_at = now(), estimated_reward = v_reward
        WHERE id = p_session_id;

    reward_credited := v_reward;
    RETURN NEXT;
END;
$$;

-- ---- admin manual balance adjustment --------------------------------
CREATE OR REPLACE FUNCTION xera_admin_adjust_balance(
    p_admin_id  BIGINT,
    p_user_id   BIGINT,
    p_amount    NUMERIC,
    p_direction TEXT,      -- 'CREDIT' or 'DEBIT'
    p_reason    TEXT
) RETURNS NUMERIC
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_wallet    xera_wallets;
    v_new_bal   NUMERIC(20,4);
    v_type      TEXT;
BEGIN
    IF p_direction NOT IN ('CREDIT','DEBIT') THEN
        RAISE EXCEPTION 'invalid_direction' USING ERRCODE = 'P0008';
    END IF;
    IF p_amount <= 0 THEN
        RAISE EXCEPTION 'invalid_amount' USING ERRCODE = 'P0009';
    END IF;

    SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        INSERT INTO xera_wallets (user_id) VALUES (p_user_id) RETURNING * INTO v_wallet;
    END IF;

    IF p_direction = 'DEBIT' AND v_wallet.cached_balance < p_amount THEN
        RAISE EXCEPTION 'insufficient_balance' USING ERRCODE = 'P0010';
    END IF;

    v_type := CASE WHEN p_direction = 'CREDIT' THEN 'ADMIN_CREDIT' ELSE 'ADMIN_DEBIT' END;

    INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, metadata)
    VALUES (v_wallet.id, p_user_id, v_type, p_amount, p_direction,
            jsonb_build_object('admin_id', p_admin_id, 'reason', p_reason));

    UPDATE xera_wallets
        SET cached_balance = cached_balance + (CASE WHEN p_direction = 'CREDIT' THEN p_amount ELSE -p_amount END),
            updated_at = now()
        WHERE id = v_wallet.id
        RETURNING cached_balance INTO v_new_bal;

    INSERT INTO xera_admin_actions (admin_id, action, old_value, new_value, reason)
    VALUES (p_admin_id, 'MANUAL_BALANCE_ADJUSTMENT',
            jsonb_build_object('user_id', p_user_id, 'balance_before', v_wallet.cached_balance),
            jsonb_build_object('user_id', p_user_id, 'balance_after', v_new_bal, 'direction', p_direction, 'amount', p_amount),
            p_reason);

    RETURN v_new_bal;
END;
$$;

-- ---- reconciliation report (section 28) -----------------------------
-- Flags any wallet whose cached_balance has drifted from the sum of its
-- ledger, and confirms the global "distributed <= allocation" invariant.
-- Never auto-corrects — admin reviews and decides.
CREATE OR REPLACE VIEW xera_reconciliation_report AS
SELECT
    w.id AS wallet_id,
    w.user_id,
    w.cached_balance,
    COALESCE(SUM(CASE WHEN t.direction = 'CREDIT' THEN t.amount ELSE -t.amount END), 0) AS ledger_balance,
    w.cached_balance - COALESCE(SUM(CASE WHEN t.direction = 'CREDIT' THEN t.amount ELSE -t.amount END), 0) AS drift
FROM xera_wallets w
LEFT JOIN xera_transactions t ON t.wallet_id = w.id AND t.status = 'CONFIRMED'
GROUP BY w.id, w.user_id, w.cached_balance
HAVING w.cached_balance <> COALESCE(SUM(CASE WHEN t.direction = 'CREDIT' THEN t.amount ELSE -t.amount END), 0);
