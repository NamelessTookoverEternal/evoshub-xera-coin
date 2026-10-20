-- ============================================================
-- XERA OFFICIAL MINING LAUNCH — schema + functions (BATCH 1)
--
-- SAFE TO RUN AS A NORMAL MIGRATION: it adds tables/functions only. It does
-- NOT reset data, does NOT change balances, and ships with the early-miner
-- bonus DISABLED (bonus_enabled = false) until the separate
-- operations/xera_official_launch_final_update.sql is run by the owner.
--
-- What this adds
--   1. xera_launch_config / xera_launch_state   launch settings + bonus counters
--   2. xera_miner_agreement_acceptances         backend-stored, versioned acceptance
--   3. xera_early_miner_bonuses                 one row per bonus recipient (max 100)
--   4. xera_launch_notice_seen                  welcome-popup completion (per user)
--   5. xera_base_reward_for_active_miners()     THE single reward-tier calculation
--   6. xera_start_mining_launch()               atomic: agreement check -> tier reward
--                                               -> session -> (optional) bonus
--   7. xera_start_mining_session() (replaced)   same signature, now a thin wrapper so
--                                               no code path can skip the agreement
--   8. xera_launch_status() / xera_launch_reconcile()   read-only status + ledger checks
--
-- Pool accounting (read this before changing anything)
--   The 75,000,000 XERA mining allocation is tracked in TWO places that must
--   move together (existing design, unchanged):
--     xera_allocations.mining_distributed          paid-out total
--     xera_mining_entitlement_state.reserved_amount paid-out + hashrate reservations
--   An early-miner bonus is credited like a daily claim: ONE ledger row (type
--   'BONUS') + wallet balance + BOTH counters, in one transaction, under the
--   same lock order (entitlement -> allocations -> wallet). Bonuses are
--   tracked separately in xera_launch_state.bonus_distributed AND by their
--   own table, but they count against the SAME 75M allocation:
--     regular_rewards = mining_distributed - bonus_distributed
--   Bonuses are NOT added to the planned supply or to the allocation.
--
-- Lock order for xera_start_mining_launch:
--   xera_launch_state -> (xera_mining_entitlement_state -> xera_allocations, only
--   when a bonus may be granted) -> xera_wallets. Matches every existing XERA
--   function (wallet is always last), so no deadlocks are introduced.
--
-- Safe to re-run: every statement is idempotent.
-- ============================================================

-- ------------------------------------------------------------
-- 1. LAUNCH CONFIG + STATE
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_launch_config (
    id                      SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    bonus_enabled           BOOLEAN NOT NULL DEFAULT false,
    bonus_max_recipients    INTEGER NOT NULL DEFAULT 100 CHECK (bonus_max_recipients BETWEEN 0 AND 100),
    bonus_amount            NUMERIC(20,4) NOT NULL DEFAULT 100 CHECK (bonus_amount > 0),
    bonus_pool_cap          NUMERIC(20,4) NOT NULL DEFAULT 10000 CHECK (bonus_pool_cap BETWEEN 0 AND 10000),
    agreement_version       TEXT NOT NULL DEFAULT 'xera-miner-agreement-2026-10-v1' CHECK (length(agreement_version) BETWEEN 1 AND 80),
    welcome_notice_version  TEXT NOT NULL DEFAULT 'xera-official-launch-2026-10-v1' CHECK (length(welcome_notice_version) BETWEEN 1 AND 80),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Defence in depth: the promotion can never be configured above 10,000 XERA.
    CONSTRAINT xera_launch_bonus_within_pool CHECK (bonus_max_recipients * bonus_amount <= bonus_pool_cap)
);
INSERT INTO xera_launch_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS xera_launch_state (
    id                  SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    bonus_slots_used    INTEGER NOT NULL DEFAULT 0 CHECK (bonus_slots_used BETWEEN 0 AND 100),
    bonus_distributed   NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK (bonus_distributed BETWEEN 0 AND 10000),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO xera_launch_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ------------------------------------------------------------
-- 2. AGREEMENT ACCEPTANCE (authoritative record, linked to the user)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_miner_agreement_acceptances (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id),
    agreement_version   TEXT NOT NULL,
    content_sha256      TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    accepted_at         TIMESTAMPTZ NOT NULL DEFAULT now(),   -- server clock, never client-supplied
    ip_address          TEXT,
    user_agent          TEXT,
    CONSTRAINT xera_agreement_one_per_user_version UNIQUE (user_id, agreement_version)
);
CREATE INDEX IF NOT EXISTS idx_xera_agreement_user ON xera_miner_agreement_acceptances(user_id);

-- ------------------------------------------------------------
-- 3. EARLY-MINER BONUS RECIPIENTS
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_early_miner_bonuses (
    user_id             BIGINT PRIMARY KEY REFERENCES users(id),          -- one bonus per account, ever
    slot_number         INTEGER NOT NULL UNIQUE CHECK (slot_number BETWEEN 1 AND 100),
    amount              NUMERIC(20,4) NOT NULL CHECK (amount > 0),
    session_id          BIGINT NOT NULL,                                  -- the session whose creation triggered it
    transaction_id      BIGINT NOT NULL,
    agreement_version   TEXT NOT NULL,
    granted_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ledger-level duplicate backstop: one early-miner BONUS row per user.
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_early_bonus_unique
    ON xera_transactions (reference_id)
    WHERE type = 'BONUS' AND reference_id LIKE 'early-miner-bonus:%';

-- ------------------------------------------------------------
-- 4. WELCOME NOTICE (so the popup is not repeated on every device)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_launch_notice_seen (
    user_id         BIGINT NOT NULL REFERENCES users(id),
    notice_version  TEXT NOT NULL,
    seen_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, notice_version)
);

-- Speeds up the active-miner count used for the reward tier.
CREATE INDEX IF NOT EXISTS idx_xera_mining_active_expiry
    ON xera_mining_sessions (expires_at) WHERE status = 'ACTIVE';

-- ------------------------------------------------------------
-- 5. THE REWARD SCHEDULE (single authoritative calculation)
-- ------------------------------------------------------------
-- p_active_miners = number of active, unexpired sessions INCLUDING the session
-- being started. The 1st..100th concurrent miner earns 10, the 101st earns 8...
-- Paid/hashrate boosts are deliberately NOT part of this function.
CREATE OR REPLACE FUNCTION xera_base_reward_for_active_miners(p_active_miners INTEGER)
RETURNS NUMERIC
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN p_active_miners <= 100  THEN 10::NUMERIC
        WHEN p_active_miners <= 200  THEN 8::NUMERIC
        WHEN p_active_miners <= 500  THEN 5::NUMERIC
        WHEN p_active_miners <= 1000 THEN 3::NUMERIC
        WHEN p_active_miners <= 1500 THEN 2.5::NUMERIC
        WHEN p_active_miners <= 2000 THEN 2::NUMERIC
        WHEN p_active_miners <= 3000 THEN 1.5::NUMERIC
        ELSE 1::NUMERIC
    END;
$$;

-- Only ACTIVE sessions that have not expired. Registered accounts are never counted.
CREATE OR REPLACE FUNCTION xera_active_miner_count()
RETURNS INTEGER
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT COUNT(*)::INTEGER FROM xera_mining_sessions
    WHERE status = 'ACTIVE' AND expires_at > now();
$$;

-- ------------------------------------------------------------
-- 6. AGREEMENT ACCEPTANCE RPC (idempotent, retry-safe)
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION xera_accept_miner_agreement(
    p_user_id       BIGINT,
    p_version       TEXT,
    p_content_hash  TEXT,
    p_ip            TEXT DEFAULT NULL,
    p_user_agent    TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_cfg     xera_launch_config;
    v_row     xera_miner_agreement_acceptances;
    v_already BOOLEAN := false;
BEGIN
    SELECT * INTO v_cfg FROM xera_launch_config WHERE id = 1;

    -- A client can only accept the version the server currently requires.
    IF p_version IS DISTINCT FROM v_cfg.agreement_version THEN
        RAISE EXCEPTION 'agreement_version_mismatch' USING ERRCODE = 'P0301';
    END IF;
    IF p_content_hash IS NULL OR p_content_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid_content_hash' USING ERRCODE = 'P0302';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM users WHERE id = p_user_id) THEN
        RAISE EXCEPTION 'user_not_found' USING ERRCODE = 'P0303';
    END IF;

    INSERT INTO xera_miner_agreement_acceptances
        (user_id, agreement_version, content_sha256, ip_address, user_agent)
    VALUES (p_user_id, p_version, p_content_hash, left(p_ip, 64), left(p_user_agent, 300))
    ON CONFLICT (user_id, agreement_version) DO NOTHING
    RETURNING * INTO v_row;

    IF v_row.id IS NULL THEN
        v_already := true;
        SELECT * INTO v_row FROM xera_miner_agreement_acceptances
         WHERE user_id = p_user_id AND agreement_version = p_version;
    ELSE
        INSERT INTO xera_security_events (user_id, event_type, details, ip_address)
        VALUES (p_user_id, 'MINER_AGREEMENT_ACCEPTED',
                jsonb_build_object('agreement_version', p_version, 'content_sha256', p_content_hash),
                left(p_ip, 64));
    END IF;

    RETURN jsonb_build_object(
        'accepted', true,
        'already_accepted', v_already,
        'agreement_version', v_row.agreement_version,
        'accepted_at', v_row.accepted_at
    );
END;
$$;

CREATE OR REPLACE FUNCTION xera_mark_launch_notice_seen(p_user_id BIGINT, p_version TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_current TEXT;
BEGIN
    SELECT welcome_notice_version INTO v_current FROM xera_launch_config WHERE id = 1;
    IF p_version IS DISTINCT FROM v_current THEN
        RAISE EXCEPTION 'notice_version_mismatch' USING ERRCODE = 'P0304';
    END IF;
    INSERT INTO xera_launch_notice_seen (user_id, notice_version)
    VALUES (p_user_id, p_version) ON CONFLICT DO NOTHING;
    RETURN true;
END;
$$;

-- ------------------------------------------------------------
-- 7. ATOMIC SESSION START (agreement -> tiered reward -> session -> bonus)
-- ------------------------------------------------------------
-- One Postgres transaction. If ANY step fails, nothing is committed: no
-- session, no bonus slot consumed, no ledger row. A bonus is only evaluated
-- AFTER the session row exists, so a failed session never costs a slot.
CREATE OR REPLACE FUNCTION xera_start_mining_launch(
    p_user_id    BIGINT,
    p_hours      INTEGER,
    p_max_reward NUMERIC
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_cfg        xera_launch_config;
    v_lstate     xera_launch_state;
    v_ent        xera_mining_entitlement_state;
    v_alloc      xera_allocations;
    v_wallet     xera_wallets;
    v_session    xera_mining_sessions;
    v_active     INTEGER;
    v_base       NUMERIC(20,4);
    v_remaining  NUMERIC(20,4);
    v_reward     NUMERIC(20,4);
    v_bonus_try  BOOLEAN;
    v_status     TEXT;
    v_slot       INTEGER := NULL;
    v_bonus_amt  NUMERIC(20,4) := 0;
    v_tx_id      BIGINT;
    v_agr_ver    TEXT;
    v_balance    NUMERIC(20,4);
BEGIN
    IF p_hours IS NULL OR p_hours <= 0 OR p_max_reward IS NULL OR p_max_reward <= 0 THEN
        RAISE EXCEPTION 'invalid_parameters' USING ERRCODE = 'P0305';
    END IF;

    SELECT * INTO v_cfg FROM xera_launch_config WHERE id = 1;

    -- Serialise every session start on this row: the tier count, the bonus slot
    -- counter and the one-bonus-per-user check are then exact under concurrency.
    SELECT * INTO v_lstate FROM xera_launch_state WHERE id = 1 FOR UPDATE;

    -- (a) Agreement must be accepted for the CURRENT version. Not bypassable.
    SELECT agreement_version INTO v_agr_ver
      FROM xera_miner_agreement_acceptances
     WHERE user_id = p_user_id AND agreement_version = v_cfg.agreement_version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'agreement_required' USING ERRCODE = 'P0300';
    END IF;

    -- (b) Existing free-mining closure rule (unchanged behaviour)
    SELECT * INTO v_ent FROM xera_mining_entitlement_state WHERE id = 1;
    IF v_ent.free_mining_closed OR v_ent.reserved_amount >= v_ent.closure_threshold THEN
        RAISE EXCEPTION 'free_mining_closed' USING ERRCODE = 'P0203';
    END IF;

    -- (c) Decide whether this start MAY receive the bonus, then take locks in
    --     the global order (entitlement -> allocations -> wallet) if so.
    v_bonus_try := v_cfg.bonus_enabled
        AND v_lstate.bonus_slots_used < v_cfg.bonus_max_recipients
        AND v_lstate.bonus_distributed + v_cfg.bonus_amount <= v_cfg.bonus_pool_cap
        AND NOT EXISTS (SELECT 1 FROM xera_early_miner_bonuses WHERE user_id = p_user_id);

    IF v_bonus_try THEN
        SELECT * INTO v_ent   FROM xera_mining_entitlement_state WHERE id = 1 FOR UPDATE;
        SELECT * INTO v_alloc FROM xera_allocations WHERE id = 1 FOR UPDATE;
    ELSE
        SELECT * INTO v_alloc FROM xera_allocations WHERE id = 1;
    END IF;

    SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        INSERT INTO xera_wallets (user_id) VALUES (p_user_id) RETURNING * INTO v_wallet;
    END IF;
    IF v_wallet.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'wallet_not_active' USING ERRCODE = 'P0001';
    END IF;

    -- (d) Tiered base reward from the live, unexpired active-session count
    --     (+1 for the session being started). Paid hashrate is separate.
    v_active    := xera_active_miner_count() + 1;
    v_base      := xera_base_reward_for_active_miners(v_active);
    v_remaining := v_alloc.mining_allocation - v_alloc.mining_distributed;
    v_reward    := LEAST(v_base, p_max_reward, GREATEST(v_remaining, 0));
    IF v_reward <= 0 THEN
        RAISE EXCEPTION 'allocation_exhausted' USING ERRCODE = 'P0006';
    END IF;

    -- (e) The session itself. One ACTIVE session per user is enforced by the
    --     partial unique index; a retry/double-click lands here.
    BEGIN
        INSERT INTO xera_mining_sessions (user_id, expires_at, rate_snapshot, estimated_reward)
        VALUES (p_user_id, now() + make_interval(hours => p_hours), v_base, v_reward)
        RETURNING * INTO v_session;
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'active_session_exists' USING ERRCODE = 'P0002';
    END;

    -- (f) Early-miner bonus — only reached when the session exists.
    IF v_bonus_try THEN
        IF v_ent.reserved_amount + v_cfg.bonus_amount > v_ent.cap
           OR v_alloc.mining_distributed + v_cfg.bonus_amount > v_alloc.mining_allocation THEN
            v_status := 'SKIPPED_ALLOCATION';   -- fail safe: session still starts, no bonus
        ELSE
            v_slot      := v_lstate.bonus_slots_used + 1;
            v_bonus_amt := v_cfg.bonus_amount;

            INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
            VALUES (v_wallet.id, p_user_id, 'BONUS', v_bonus_amt, 'CREDIT',
                    'early-miner-bonus:' || p_user_id::text,
                    jsonb_build_object('promotion', 'early-miner-2026-10', 'slot', v_slot,
                                       'session_id', v_session.id,
                                       'agreement_version', v_cfg.agreement_version))
            RETURNING id INTO v_tx_id;

            INSERT INTO xera_early_miner_bonuses
                (user_id, slot_number, amount, session_id, transaction_id, agreement_version)
            VALUES (p_user_id, v_slot, v_bonus_amt, v_session.id, v_tx_id, v_cfg.agreement_version);

            UPDATE xera_wallets
               SET cached_balance = cached_balance + v_bonus_amt, updated_at = now()
             WHERE id = v_wallet.id;

            UPDATE xera_allocations
               SET mining_distributed = mining_distributed + v_bonus_amt, updated_at = now()
             WHERE id = 1;

            UPDATE xera_mining_entitlement_state
               SET reserved_amount = reserved_amount + v_bonus_amt,
                   free_mining_closed = free_mining_closed OR (reserved_amount + v_bonus_amt >= closure_threshold),
                   updated_at = now()
             WHERE id = 1;

            UPDATE xera_launch_state
               SET bonus_slots_used = bonus_slots_used + 1,
                   bonus_distributed = bonus_distributed + v_bonus_amt,
                   updated_at = now()
             WHERE id = 1;

            v_status := 'GRANTED';
        END IF;
    ELSIF NOT v_cfg.bonus_enabled THEN
        v_status := 'DISABLED';
    ELSIF EXISTS (SELECT 1 FROM xera_early_miner_bonuses WHERE user_id = p_user_id) THEN
        v_status := 'ALREADY_RECEIVED';
    ELSE
        v_status := 'SLOTS_FULL';
    END IF;

    SELECT cached_balance INTO v_balance FROM xera_wallets WHERE id = v_wallet.id;

    RETURN jsonb_build_object(
        'session_id',       v_session.id,
        'user_id',          v_session.user_id,
        'started_at',       v_session.started_at,
        'expires_at',       v_session.expires_at,
        'status',           v_session.status,
        'rate_snapshot',    v_session.rate_snapshot,
        'estimated_reward', v_session.estimated_reward,
        'active_miners',    v_active,
        'bonus_status',     v_status,
        'bonus_amount',     v_bonus_amt,
        'bonus_slot',       v_slot,
        'new_balance',      v_balance
    );
END;
$$;

-- The pre-launch entry point keeps its signature so existing callers still
-- work, but it can no longer skip the agreement or choose its own rate:
-- p_rate is IGNORED, the reward always comes from the schedule above.
CREATE OR REPLACE FUNCTION xera_start_mining_session(
    p_user_id    BIGINT,
    p_rate       NUMERIC,
    p_hours      INTEGER,
    p_max_reward NUMERIC
) RETURNS xera_mining_sessions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_out     JSONB;
    v_session xera_mining_sessions;
BEGIN
    v_out := xera_start_mining_launch(p_user_id, p_hours, p_max_reward);
    SELECT * INTO v_session FROM xera_mining_sessions WHERE id = (v_out->>'session_id')::BIGINT;
    RETURN v_session;
END;
$$;

-- ------------------------------------------------------------
-- 8. READ-ONLY STATUS (no private data) + RECONCILIATION
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION xera_launch_status(p_user_id BIGINT DEFAULT NULL)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_cfg    xera_launch_config;
    v_state  xera_launch_state;
    v_alloc  xera_allocations;
    v_active INTEGER;
    v_next   INTEGER;
    v_slots_left INTEGER;
    v_out    JSONB;
BEGIN
    SELECT * INTO v_cfg   FROM xera_launch_config WHERE id = 1;
    SELECT * INTO v_state FROM xera_launch_state  WHERE id = 1;
    SELECT * INTO v_alloc FROM xera_allocations   WHERE id = 1;

    v_active := xera_active_miner_count();
    v_next   := v_active + 1;
    v_slots_left := CASE WHEN v_cfg.bonus_enabled
                         THEN GREATEST(v_cfg.bonus_max_recipients - v_state.bonus_slots_used, 0)
                         ELSE 0 END;

    -- Public part: aggregate numbers only.
    v_out := jsonb_build_object(
        'active_miners',          v_active,
        'next_miner_position',    v_next,
        'base_reward_estimate',   LEAST(xera_base_reward_for_active_miners(v_next),
                                        GREATEST(v_alloc.mining_allocation - v_alloc.mining_distributed, 0)),
        'bonus_enabled',          v_cfg.bonus_enabled,
        'bonus_amount',           v_cfg.bonus_amount,
        'bonus_total_slots',      v_cfg.bonus_max_recipients,
        'bonus_slots_remaining',  v_slots_left,
        'agreement_version',      v_cfg.agreement_version,
        'welcome_notice_version', v_cfg.welcome_notice_version
    );

    -- Per-user part: only about the authenticated caller, supplied by the backend.
    IF p_user_id IS NOT NULL THEN
        v_out := v_out || jsonb_build_object(
            'agreement_accepted', EXISTS (
                SELECT 1 FROM xera_miner_agreement_acceptances
                 WHERE user_id = p_user_id AND agreement_version = v_cfg.agreement_version),
            'bonus_received', EXISTS (SELECT 1 FROM xera_early_miner_bonuses WHERE user_id = p_user_id),
            'welcome_seen', EXISTS (
                SELECT 1 FROM xera_launch_notice_seen
                 WHERE user_id = p_user_id AND notice_version = v_cfg.welcome_notice_version)
        );
    END IF;
    RETURN v_out;
END;
$$;

-- Owner/ops check: every value in "problems" must be 0 / empty.
CREATE OR REPLACE FUNCTION xera_launch_reconcile()
RETURNS JSONB
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_alloc   xera_allocations;
    v_ent     xera_mining_entitlement_state;
    v_state   xera_launch_state;
    v_ledger_distributed NUMERIC;
    v_bad_wallets        INTEGER;
    v_neg_wallets        INTEGER;
    v_bonus_rows         INTEGER;
    v_bonus_sum          NUMERIC;
    v_bonus_ledger       NUMERIC;
    v_problems JSONB := '[]'::jsonb;
BEGIN
    SELECT * INTO v_alloc FROM xera_allocations WHERE id = 1;
    SELECT * INTO v_ent   FROM xera_mining_entitlement_state WHERE id = 1;
    SELECT * INTO v_state FROM xera_launch_state WHERE id = 1;

    -- Everything paid out of the 75M pool: free/hashrate rewards, daily claims, early bonuses.
    SELECT COALESCE(SUM(t.amount), 0) INTO v_ledger_distributed
      FROM xera_transactions t
     WHERE t.direction = 'CREDIT' AND t.status = 'CONFIRMED'
       AND (t.type IN ('MINING_REWARD', 'DAILY_CLAIM')
            OR (t.type = 'BONUS' AND t.reference_id LIKE 'early-miner-bonus:%'));

    SELECT COUNT(*) INTO v_bad_wallets
      FROM xera_wallets w
     WHERE w.cached_balance <> COALESCE((
            SELECT SUM(CASE WHEN t.direction = 'CREDIT' THEN t.amount ELSE -t.amount END)
              FROM xera_transactions t WHERE t.wallet_id = w.id AND t.status = 'CONFIRMED'), 0);

    SELECT COUNT(*) INTO v_neg_wallets FROM xera_wallets WHERE cached_balance < 0;
    SELECT COUNT(*), COALESCE(SUM(amount), 0) INTO v_bonus_rows, v_bonus_sum FROM xera_early_miner_bonuses;
    SELECT COALESCE(SUM(amount), 0) INTO v_bonus_ledger FROM xera_transactions
     WHERE type = 'BONUS' AND reference_id LIKE 'early-miner-bonus:%' AND direction = 'CREDIT';

    IF v_ledger_distributed <> v_alloc.mining_distributed THEN
        v_problems := v_problems || jsonb_build_array('mining_distributed_differs_from_ledger');
    END IF;
    IF v_bad_wallets > 0 THEN v_problems := v_problems || jsonb_build_array('wallet_cache_differs_from_ledger'); END IF;
    IF v_neg_wallets > 0 THEN v_problems := v_problems || jsonb_build_array('negative_wallet_balance'); END IF;
    IF v_bonus_rows <> v_state.bonus_slots_used THEN v_problems := v_problems || jsonb_build_array('bonus_slots_used_differs_from_rows'); END IF;
    IF v_bonus_sum <> v_state.bonus_distributed OR v_bonus_sum <> v_bonus_ledger THEN
        v_problems := v_problems || jsonb_build_array('bonus_total_differs_from_ledger');
    END IF;
    IF v_bonus_rows > 100 OR v_bonus_sum > 10000 THEN v_problems := v_problems || jsonb_build_array('bonus_limit_exceeded'); END IF;
    IF v_alloc.mining_distributed > v_alloc.mining_allocation THEN v_problems := v_problems || jsonb_build_array('allocation_exceeded'); END IF;
    IF v_ent.reserved_amount < v_alloc.mining_distributed THEN v_problems := v_problems || jsonb_build_array('entitlement_below_distributed'); END IF;
    IF v_alloc.total_target <> 500000000 OR v_alloc.mining_allocation <> 75000000 THEN
        v_problems := v_problems || jsonb_build_array('supply_or_allocation_changed');
    END IF;

    RETURN jsonb_build_object(
        'ok',                      jsonb_array_length(v_problems) = 0,
        'problems',                v_problems,
        'mining_distributed',      v_alloc.mining_distributed,
        'ledger_distributed',      v_ledger_distributed,
        'bonus_distributed',       v_state.bonus_distributed,
        'regular_rewards',         v_alloc.mining_distributed - v_state.bonus_distributed,
        'bonus_recipients',        v_bonus_rows,
        'entitlement_reserved',    v_ent.reserved_amount,
        'mining_allocation',       v_alloc.mining_allocation,
        'remaining_allocation',    v_alloc.mining_allocation - v_alloc.mining_distributed
    );
END;
$$;

-- ------------------------------------------------------------
-- 9. PRIVILEGES — same default-deny posture as the rest of XERA.
--    The backend uses the service_role key; the browser never calls these.
-- ------------------------------------------------------------
ALTER TABLE xera_launch_config               ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_launch_state                ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_miner_agreement_acceptances ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_early_miner_bonuses         ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_launch_notice_seen          ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON xera_launch_config, xera_launch_state, xera_miner_agreement_acceptances,
              xera_early_miner_bonuses, xera_launch_notice_seen FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON xera_launch_config, xera_launch_state, xera_miner_agreement_acceptances,
              xera_early_miner_bonuses, xera_launch_notice_seen TO service_role;
GRANT USAGE, SELECT ON SEQUENCE xera_miner_agreement_acceptances_id_seq TO service_role;

REVOKE ALL ON FUNCTION xera_base_reward_for_active_miners(INTEGER)                 FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION xera_active_miner_count()                                   FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION xera_accept_miner_agreement(BIGINT, TEXT, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION xera_mark_launch_notice_seen(BIGINT, TEXT)                  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION xera_start_mining_launch(BIGINT, INTEGER, NUMERIC)          FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION xera_start_mining_session(BIGINT, NUMERIC, INTEGER, NUMERIC) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION xera_launch_status(BIGINT)                                  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION xera_launch_reconcile()                                     FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION xera_base_reward_for_active_miners(INTEGER)                 TO service_role;
GRANT EXECUTE ON FUNCTION xera_active_miner_count()                                   TO service_role;
GRANT EXECUTE ON FUNCTION xera_accept_miner_agreement(BIGINT, TEXT, TEXT, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION xera_mark_launch_notice_seen(BIGINT, TEXT)                  TO service_role;
GRANT EXECUTE ON FUNCTION xera_start_mining_launch(BIGINT, INTEGER, NUMERIC)          TO service_role;
GRANT EXECUTE ON FUNCTION xera_start_mining_session(BIGINT, NUMERIC, INTEGER, NUMERIC) TO service_role;
GRANT EXECUTE ON FUNCTION xera_launch_status(BIGINT)                                  TO service_role;
GRANT EXECUTE ON FUNCTION xera_launch_reconcile()                                     TO service_role;
