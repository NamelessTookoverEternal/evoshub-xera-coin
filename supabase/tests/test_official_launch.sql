-- XERA official launch — SQL tests (BATCH 1).
-- Run against a DISPOSABLE database built by ./setup_xera_test_db.sh, after
-- applying migrations/20261020_xera_official_mining_rewards.sql and
-- migrations/20261021_xera_official_launch_v1.sql. See run_launch_tests.sh.
-- Every assertion raises on failure; psql runs with ON_ERROR_STOP.
\set ON_ERROR_STOP on
\set QUIET on

CREATE OR REPLACE FUNCTION _t_ok(c BOOLEAN, m TEXT) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN IF c IS NOT TRUE THEN RAISE EXCEPTION 'ASSERTION FAILED: %', m; END IF; END $$;

-- Runs a statement and returns the exception message ('' when it succeeds).
CREATE OR REPLACE FUNCTION _t_err(q TEXT) RETURNS TEXT LANGUAGE plpgsql AS $$
BEGIN EXECUTE q; RETURN ''; EXCEPTION WHEN OTHERS THEN RETURN SQLERRM; END $$;

CREATE OR REPLACE FUNCTION _t_user(p_id BIGINT) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN INSERT INTO users (id, username) VALUES (p_id, 'u' || p_id) ON CONFLICT DO NOTHING; END $$;

CREATE OR REPLACE FUNCTION _t_accept(p_id BIGINT) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE v TEXT;
BEGIN
    SELECT agreement_version INTO v FROM xera_launch_config WHERE id = 1;
    PERFORM xera_accept_miner_agreement(p_id, v, repeat('a', 64), '127.0.0.1', 'test');
END $$;

CREATE OR REPLACE FUNCTION _t_start(p_id BIGINT) RETURNS JSONB LANGUAGE sql AS $$
    SELECT xera_start_mining_launch(p_id, 24, 5000);
$$;

-- ---------------------------------------------------------------------------
-- 1. REWARD TIERS — every boundary
-- ---------------------------------------------------------------------------
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN SELECT * FROM (VALUES
        (0,10),(1,10),(100,10),(101,8),(200,8),(201,5),(500,5),(501,3),(1000,3),
        (1001,2.5),(1500,2.5),(1501,2),(2000,2),(2001,1.5),(3000,1.5),(3001,1),(3002,1),(1000000,1)
    ) AS x(n, expected) LOOP
        PERFORM _t_ok(xera_base_reward_for_active_miners(r.n) = r.expected,
                      format('tier for %s miners should be %s, got %s', r.n, r.expected, xera_base_reward_for_active_miners(r.n)));
    END LOOP;
    PERFORM _t_ok((SELECT MIN(xera_base_reward_for_active_miners(g)) FROM generate_series(1, 5000) g) = 1, 'minimum base reward is 1');
END $$;

-- ---------------------------------------------------------------------------
-- 2. DAILY CLAIM = 2 XERA, no duplicates, counted in the pool
-- ---------------------------------------------------------------------------
SELECT _t_user(1);
DO $$
DECLARE v_cfg NUMERIC; v_dist0 NUMERIC; v_res RECORD;
BEGIN
    SELECT reward_amount INTO v_cfg FROM xera_daily_config WHERE id = 1;
    PERFORM _t_ok(v_cfg = 2, 'daily reward configured to 2 (got ' || v_cfg || ')');
    SELECT mining_distributed INTO v_dist0 FROM xera_allocations WHERE id = 1;
    SELECT * INTO v_res FROM xera_claim_daily_reward(1, v_cfg);
    PERFORM _t_ok(v_res.reward_credited = 2 AND v_res.new_balance = 2, 'daily claim credits exactly 2');
    PERFORM _t_ok(_t_err('SELECT * FROM xera_claim_daily_reward(1, 2)') LIKE '%already_claimed_today%', 'duplicate daily claim rejected');
    PERFORM _t_ok((SELECT mining_distributed FROM xera_allocations WHERE id = 1) = v_dist0 + 2, 'daily claim counted in mining_distributed once');
    PERFORM _t_ok((SELECT COUNT(*) FROM xera_transactions WHERE user_id = 1 AND type = 'DAILY_CLAIM') = 1, 'exactly one DAILY_CLAIM ledger row');
    PERFORM _t_ok((xera_launch_reconcile()->>'ok')::boolean, 'reconcile ok after daily claim: ' || (xera_launch_reconcile())::text);
END $$;

-- ---------------------------------------------------------------------------
-- 3. AGREEMENT ENFORCED IN THE BACKEND DATABASE FUNCTION
-- ---------------------------------------------------------------------------
SELECT _t_user(2); SELECT _t_user(3);
DO $$
DECLARE v TEXT; r JSONB; n0 INTEGER;
BEGIN
    SELECT agreement_version INTO v FROM xera_launch_config WHERE id = 1;

    PERFORM _t_ok(_t_err('SELECT _t_start(2)') LIKE '%agreement_required%', 'start without acceptance is refused');
    PERFORM _t_ok(NOT EXISTS (SELECT 1 FROM xera_mining_sessions WHERE user_id = 2), 'no session created without acceptance');
    PERFORM _t_ok(_t_err('SELECT xera_start_mining_session(2, 999, 24, 5000)') LIKE '%agreement_required%', 'legacy entry point also enforces the agreement');

    PERFORM _t_ok(_t_err(format('SELECT xera_accept_miner_agreement(2, %L, %L)', 'wrong-version', repeat('a',64))) LIKE '%agreement_version_mismatch%', 'wrong version rejected');
    PERFORM _t_ok(_t_err(format('SELECT xera_accept_miner_agreement(2, %L, %L)', v, 'nothex')) LIKE '%invalid_content_hash%', 'bad content hash rejected');
    PERFORM _t_ok(_t_err(format('SELECT xera_accept_miner_agreement(424242, %L, %L)', v, repeat('a',64))) LIKE '%user_not_found%', 'unknown user rejected');
    PERFORM _t_ok(_t_err('SELECT _t_start(2)') LIKE '%agreement_required%', 'rejected acceptances do not unlock mining');

    r := xera_accept_miner_agreement(2, v, repeat('b', 64), '1.2.3.4', 'ua');
    PERFORM _t_ok((r->>'accepted')::boolean AND NOT (r->>'already_accepted')::boolean, 'first acceptance recorded');
    r := xera_accept_miner_agreement(2, v, repeat('b', 64), '1.2.3.4', 'ua');
    PERFORM _t_ok((r->>'already_accepted')::boolean, 'retry is idempotent');
    PERFORM _t_ok((SELECT COUNT(*) FROM xera_miner_agreement_acceptances WHERE user_id = 2) = 1, 'single acceptance row after retry');
    PERFORM _t_ok((SELECT accepted_at FROM xera_miner_agreement_acceptances WHERE user_id = 2) <= now(), 'timestamp is server-side');

    -- user isolation: user 2 accepting does not unlock user 3
    PERFORM _t_ok(_t_err('SELECT _t_start(3)') LIKE '%agreement_required%', 'acceptance is per user');

    -- version change forces re-acceptance
    UPDATE xera_launch_config SET agreement_version = 'xera-miner-agreement-TEST-v2' WHERE id = 1;
    PERFORM _t_ok(_t_err('SELECT _t_start(2)') LIKE '%agreement_required%', 'a new agreement version requires re-acceptance');
    PERFORM xera_accept_miner_agreement(2, 'xera-miner-agreement-TEST-v2', repeat('c', 64));
    r := _t_start(2);
    PERFORM _t_ok(r->>'bonus_status' = 'DISABLED', 'bonus is DISABLED until the final-update script enables it');
    UPDATE xera_mining_sessions SET status = 'CANCELLED' WHERE user_id = 2;
    UPDATE xera_launch_config SET agreement_version = v WHERE id = 1;
    PERFORM _t_ok((xera_launch_status(2)->>'agreement_accepted')::boolean AND NOT (xera_launch_status(3)->>'agreement_accepted')::boolean, 'status reflects acceptance per user and version');
END $$;

-- ---------------------------------------------------------------------------
-- 4. FIRST-100 BONUS — grant, accounting, duplicates, failures
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    r JSONB; b0 NUMERIC; d0 NUMERIC; e0 NUMERIC;
BEGIN
    UPDATE xera_launch_config SET bonus_enabled = true WHERE id = 1;
    -- user 2 already accepted the real version in section 3? Make sure.
    PERFORM _t_accept(2);
    SELECT mining_distributed INTO d0 FROM xera_allocations WHERE id = 1;
    SELECT reserved_amount INTO e0 FROM xera_mining_entitlement_state WHERE id = 1;

    r := _t_start(2);
    PERFORM _t_ok(r->>'bonus_status' = 'GRANTED' AND (r->>'bonus_slot')::int = 1 AND (r->>'bonus_amount')::numeric = 100, 'first eligible miner gets slot 1 / 100 XERA: ' || r::text);
    PERFORM _t_ok((r->>'rate_snapshot')::numeric = 10 AND (r->>'estimated_reward')::numeric = 10, 'base reward is 10 for the 1st active miner');
    PERFORM _t_ok((r->>'new_balance')::numeric = 100, 'wallet credited exactly 100');
    PERFORM _t_ok((SELECT mining_distributed FROM xera_allocations WHERE id = 1) = d0 + 100, 'bonus counted once in mining_distributed');
    PERFORM _t_ok((SELECT reserved_amount FROM xera_mining_entitlement_state WHERE id = 1) = e0 + 100, 'bonus counted once in entitlement ledger');
    PERFORM _t_ok((SELECT bonus_slots_used = 1 AND bonus_distributed = 100 FROM xera_launch_state WHERE id = 1), 'bonus tracked separately in launch state');
    PERFORM _t_ok((SELECT COUNT(*) FROM xera_transactions WHERE user_id = 2 AND type = 'BONUS') = 1, 'one BONUS ledger row');
    PERFORM _t_ok((xera_launch_reconcile()->>'ok')::boolean, 'reconcile ok after bonus: ' || xera_launch_reconcile()::text);
    PERFORM _t_ok((xera_launch_reconcile()->>'regular_rewards')::numeric = 2, 'regular rewards (2 daily) are separate from the 100 bonus');

    -- double click / retry while active
    PERFORM _t_ok(_t_err('SELECT _t_start(2)') LIKE '%active_session_exists%', 'second start while active is rejected');
    PERFORM _t_ok((SELECT COUNT(*) FROM xera_mining_sessions WHERE user_id = 2 AND status = 'ACTIVE') = 1, 'still exactly one active session');
    PERFORM _t_ok((SELECT bonus_slots_used FROM xera_launch_state WHERE id = 1) = 1, 'rejected retry consumed no slot');

    -- restart after the session ends: NO second bonus
    UPDATE xera_mining_sessions SET status = 'CANCELLED' WHERE user_id = 2;
    r := _t_start(2);
    PERFORM _t_ok(r->>'bonus_status' = 'ALREADY_RECEIVED', 'restart does not re-award: ' || r::text);
    PERFORM _t_ok((r->>'new_balance')::numeric = 100, 'balance unchanged on restart');
    PERFORM _t_ok((SELECT COUNT(*) FROM xera_transactions WHERE type = 'BONUS') = 1, 'still one BONUS row');
    UPDATE xera_mining_sessions SET status = 'CANCELLED' WHERE user_id = 2;

    -- login/refresh/acceptance never grant: acceptance for a new user creates no bonus
    PERFORM _t_user(4);
    PERFORM _t_accept(4);
    PERFORM _t_ok(NOT EXISTS (SELECT 1 FROM xera_early_miner_bonuses WHERE user_id = 4), 'accepting the agreement alone grants nothing');
    PERFORM xera_launch_status(4);
    PERFORM _t_ok(NOT EXISTS (SELECT 1 FROM xera_early_miner_bonuses WHERE user_id = 4), 'reading status grants nothing');

    -- existing wallets are not auto-awarded
    PERFORM _t_ok((SELECT COUNT(*) FROM xera_early_miner_bonuses) = 1, 'only the miner who started a session has a bonus');
END $$;

-- failures must not consume a slot
DO $$
DECLARE s0 INTEGER; d0 NUMERIC;
BEGIN
    PERFORM _t_user(5); PERFORM _t_accept(5);
    INSERT INTO xera_wallets (user_id, status) VALUES (5, 'SUSPENDED');
    SELECT bonus_slots_used INTO s0 FROM xera_launch_state WHERE id = 1;
    PERFORM _t_ok(_t_err('SELECT _t_start(5)') LIKE '%wallet_not_active%', 'suspended wallet cannot start');
    PERFORM _t_ok((SELECT bonus_slots_used FROM xera_launch_state WHERE id = 1) = s0, 'failed start consumed no bonus slot');
    PERFORM _t_ok(NOT EXISTS (SELECT 1 FROM xera_mining_sessions WHERE user_id = 5), 'failed start left no session');
    PERFORM _t_ok(NOT EXISTS (SELECT 1 FROM xera_transactions WHERE user_id = 5), 'failed start left no ledger row');
    UPDATE xera_wallets SET status = 'ACTIVE' WHERE user_id = 5;

    -- allocation exhausted: no session, no slot
    SELECT mining_distributed INTO d0 FROM xera_allocations WHERE id = 1;
    UPDATE xera_allocations SET mining_distributed = mining_allocation WHERE id = 1;
    PERFORM _t_ok(_t_err('SELECT _t_start(5)') LIKE '%allocation_exhausted%', 'exhausted allocation blocks session start');
    PERFORM _t_ok((SELECT bonus_slots_used FROM xera_launch_state WHERE id = 1) = s0, 'exhausted start consumed no slot');
    UPDATE xera_allocations SET mining_distributed = d0 WHERE id = 1;
END $$;

-- ---------------------------------------------------------------------------
-- 5. 100-RECIPIENT MAXIMUM + TIER BOUNDARIES THROUGH REAL SESSIONS
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    i INTEGER; r JSONB; granted INTEGER := 1;   -- user 2 already holds slot 1 (session cancelled)
    v_active INTEGER;
BEGIN
    -- user 5 is miner #1 (session active), then users 100..198 -> 100 active miners total
    r := _t_start(5);
    PERFORM _t_ok((r->>'rate_snapshot')::numeric = 10 AND r->>'bonus_status' = 'GRANTED' AND (r->>'bonus_slot')::int = 2, 'user 5 is slot 2');
    FOR i IN 100..197 LOOP
        PERFORM _t_user(i); PERFORM _t_accept(i);
        r := _t_start(i);
        PERFORM _t_ok((r->>'rate_snapshot')::numeric = 10, 'miners 1..100 earn 10 (miner at user ' || i || ')');
    END LOOP;
    SELECT xera_active_miner_count() INTO v_active;
    PERFORM _t_ok(v_active = 99, 'active miner count is 99 (got ' || v_active || ')');
    PERFORM _t_ok((SELECT bonus_slots_used FROM xera_launch_state WHERE id = 1) = 100, 'slot 100 reached by the 100th recipient');

    -- 100th active miner
    PERFORM _t_user(300); PERFORM _t_accept(300);
    r := _t_start(300);
    PERFORM _t_ok((r->>'rate_snapshot')::numeric = 10 AND (r->>'active_miners')::int = 100, '100th active miner still earns 10');

    -- 101st active miner: tier drops to 8 and there are no bonus slots left
    PERFORM _t_user(301); PERFORM _t_accept(301);
    r := _t_start(301);
    PERFORM _t_ok((r->>'rate_snapshot')::numeric = 8 AND (r->>'active_miners')::int = 101, '101st active miner earns 8: ' || r::text);
    PERFORM _t_ok(r->>'bonus_status' = 'SLOTS_FULL', 'no bonus after the 100th recipient: ' || r::text);

    PERFORM _t_ok((SELECT COUNT(*) FROM xera_early_miner_bonuses) = 100, 'exactly 100 bonus recipients');
    PERFORM _t_ok((SELECT SUM(amount) FROM xera_early_miner_bonuses) = 10000, 'bonus total is exactly 10,000');
    PERFORM _t_ok((SELECT bonus_distributed FROM xera_launch_state WHERE id = 1) = 10000, 'bonus_distributed = 10,000');
    PERFORM _t_ok((xera_launch_reconcile()->>'ok')::boolean, 'reconcile ok at 100 recipients: ' || xera_launch_reconcile()::text);
    PERFORM _t_ok((xera_launch_status()->>'bonus_slots_remaining')::int = 0, 'status shows 0 slots remaining');
    PERFORM _t_ok(NOT (xera_launch_status() ? 'user_id') AND NOT (xera_launch_status()::text ILIKE '%username%'), 'public status exposes no account data');
END $$;

-- expired sessions are not counted (and status ACTIVE alone is not enough)
DO $$
DECLARE r JSONB; before_n INTEGER;
BEGIN
    SELECT xera_active_miner_count() INTO before_n;
    PERFORM _t_ok(before_n = 101, 'count before expiry = 101 (got ' || before_n || ')');
    UPDATE xera_mining_sessions SET expires_at = now() - interval '1 minute' WHERE user_id = 301;   -- still status ACTIVE
    PERFORM _t_ok(xera_active_miner_count() = 100, 'an expired-but-unclaimed session is not an active miner');
    PERFORM _t_ok((xera_launch_status()->>'base_reward_estimate')::numeric = 8 AND (xera_launch_status()->>'next_miner_position')::int = 101, 'status estimate matches the tier for the next position (#101 -> 8)');
    PERFORM _t_ok(xera_active_miner_count() < (SELECT COUNT(*) FROM users), 'registered accounts are not counted as miners');
END $$;

-- ---------------------------------------------------------------------------
-- 6. ALLOCATION LIMITS — bonus + rewards share the 75M
-- ---------------------------------------------------------------------------
DO $$
DECLARE r JSONB; d0 NUMERIC; e0 NUMERIC; s0 INTEGER;
BEGIN
    -- fresh recipient pool for this check
    UPDATE xera_launch_state SET bonus_slots_used = 0, bonus_distributed = 0 WHERE id = 1;
    DELETE FROM xera_early_miner_bonuses;
    DELETE FROM xera_transactions WHERE type = 'BONUS';
    UPDATE xera_wallets SET cached_balance = 0 WHERE true;
    -- rebuild a consistent baseline for the arithmetic below
    UPDATE xera_allocations SET mining_distributed = 74999950 WHERE id = 1;
    UPDATE xera_mining_entitlement_state SET reserved_amount = 74999950, closure_threshold = 75000000, free_mining_closed = false WHERE id = 1;
    UPDATE xera_mining_sessions SET status = 'CANCELLED';

    PERFORM _t_user(400); PERFORM _t_accept(400);
    SELECT bonus_slots_used INTO s0 FROM xera_launch_state WHERE id = 1;
    r := _t_start(400);
    PERFORM _t_ok(r->>'bonus_status' = 'SKIPPED_ALLOCATION', 'bonus that would exceed the 75M is skipped (fail safe): ' || r::text);
    PERFORM _t_ok(r->>'session_id' IS NOT NULL, 'the session itself still starts');
    PERFORM _t_ok((r->>'estimated_reward')::numeric = 10, 'reward is clamped to remaining capacity (50 >= 10)');
    PERFORM _t_ok((SELECT bonus_slots_used FROM xera_launch_state WHERE id = 1) = s0, 'skipped bonus consumed no slot');
    PERFORM _t_ok((SELECT mining_distributed FROM xera_allocations WHERE id = 1) = 74999950, 'skipped bonus did not move mining_distributed');
    PERFORM _t_ok((SELECT mining_distributed <= mining_allocation FROM xera_allocations WHERE id = 1), 'never above the allocation');

    -- config can never exceed the 10,000 XERA promotion ceiling
    PERFORM _t_ok(_t_err('UPDATE xera_launch_config SET bonus_amount = 101 WHERE id = 1') LIKE '%xera_launch_bonus_within_pool%', '100 x 101 > 10,000 is rejected');
    PERFORM _t_ok(_t_err('UPDATE xera_launch_config SET bonus_max_recipients = 101 WHERE id = 1') <> '', '101 recipients is rejected');
    PERFORM _t_ok(_t_err('UPDATE xera_launch_config SET bonus_pool_cap = 20000 WHERE id = 1') <> '', 'pool cap above 10,000 is rejected');
    PERFORM _t_ok(_t_err('INSERT INTO xera_early_miner_bonuses (user_id, slot_number, amount, session_id, transaction_id, agreement_version) VALUES (400, 101, 100, 1, 1, ''x'')') <> '', 'slot 101 is rejected');
    PERFORM _t_ok((SELECT total_target = 500000000 AND mining_allocation = 75000000 FROM xera_allocations WHERE id = 1), 'supply and allocation unchanged');
END $$;

-- ---------------------------------------------------------------------------
-- 7. PRIVILEGES — browser roles cannot reach any of it
-- ---------------------------------------------------------------------------
DO $$
DECLARE f TEXT;
BEGIN
    FOREACH f IN ARRAY ARRAY[
        'xera_start_mining_launch(bigint,integer,numeric)',
        'xera_start_mining_session(bigint,numeric,integer,numeric)',
        'xera_accept_miner_agreement(bigint,text,text,text,text)',
        'xera_launch_reconcile()', 'xera_launch_status(bigint)'] LOOP
        PERFORM _t_ok(NOT has_function_privilege('anon', f, 'EXECUTE'), 'anon cannot execute ' || f);
        PERFORM _t_ok(NOT has_function_privilege('authenticated', f, 'EXECUTE'), 'authenticated cannot execute ' || f);
        PERFORM _t_ok(has_function_privilege('service_role', f, 'EXECUTE'), 'service_role can execute ' || f);
    END LOOP;
    PERFORM _t_ok(NOT has_table_privilege('anon', 'xera_miner_agreement_acceptances', 'SELECT'), 'anon cannot read acceptances');
    PERFORM _t_ok(NOT has_table_privilege('authenticated', 'xera_early_miner_bonuses', 'SELECT'), 'authenticated cannot read bonuses');
    PERFORM _t_ok((SELECT relrowsecurity FROM pg_class WHERE relname = 'xera_launch_config'), 'RLS enabled on launch config');
END $$;

\echo 'ALL LAUNCH SQL TESTS PASSED'
