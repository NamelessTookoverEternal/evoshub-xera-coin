-- ============================================================================
-- XERA OFFICIAL LAUNCH — TEST-DATA RESET   (MANUAL, ONE-TIME, OWNER-RUN)
-- ============================================================================
-- Paste into the Supabase SQL Editor of the PRODUCTION project and run.
-- This file is NOT a migration. Nothing runs it automatically.
--
-- BEFORE YOU RUN IT
--   1. Deploy the new backend, and apply migrations/20261021_xera_official_launch_v1.sql.
--   2. Change the confirmation word in STEP 1 below from 'NO' to
--      'YES-RESET-XERA-TEST-DATA'. (Stops an accidental paste-and-run.)
--   3. Run the whole file at once. It is ONE transaction: if any check fails,
--      everything rolls back and nothing is changed.
--
-- WHAT IT CHANGES (XERA test data only)
--   * Copies the affected tables into a private schema `xera_backup_launch_reset`
--     (RLS on, no access for anon/authenticated). Backups are never deleted.
--   * Deletes ledger rows:      xera_transactions
--   * Deletes mining sessions:  xera_mining_sessions
--   * Sets every xera_wallets.cached_balance to 0           (wallet rows are KEPT)
--   * Zeroes daily-claim progress (last_claim_date, streak, total_claims)   (rows KEPT)
--   * Sets xera_allocations.mining_distributed to 0         (allocation amounts UNCHANGED)
--   * Re-bases xera_mining_entitlement_state.reserved_amount to the capacity still
--     held by PAID hashrate sessions (see "Hashrate" below), not blindly to 0.
--
-- WHAT IT NEVER TOUCHES
--   users, auth records, wallet identities/status, linked external wallets,
--   EVOS Data / EVOSGPT / other product tables, blockchain contracts, the 500M
--   total supply, the 75M mining allocation, hashrate tiers/sessions/payments,
--   referral links, on-chain claim records, ID sequences.
--
-- HASHRATE (paid boosts) — read this
--   Hashrate sessions/payments are financial records, so they are preserved.
--   Capacity they still hold stays reserved so the 75M cap remains correct:
--       reserved_amount = SUM(reserved_entitlement - rewarded_amount)
--                         over sessions in PENDING_PAYMENT / ACTIVE.
--   If you used hashrate purchases ONLY for testing and want them cleared too,
--   that is a separate owner decision — this script deliberately does not.
--
-- ON-CHAIN CLAIMS
--   The script ABORTS if xera_onchain_claims has any rows (or the on-chain
--   counter is non-zero), because the claimable-balance formula subtracts every
--   historical on-chain claim and old test claims would silently reduce what
--   launch users can claim later. Decide how to treat them first.
--
-- ROLLBACK: see operations/xera_official_launch_rollback.sql (only valid before
--   launch activity starts) and operations/XERA_LAUNCH_RUNBOOK.md.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '15s';
SET LOCAL statement_timeout = '120s';

-- ---------------------------------------------------------------------------
-- STEP 1 — explicit confirmation
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_confirm TEXT := 'NO';      -- <<< change to 'YES-RESET-XERA-TEST-DATA' to run
BEGIN
    IF v_confirm IS DISTINCT FROM 'YES-RESET-XERA-TEST-DATA' THEN
        RAISE EXCEPTION 'Reset not confirmed. Edit v_confirm in STEP 1 to run. Nothing was changed.';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- STEP 2 — schema preconditions (abort if anything expected is missing)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    t TEXT;
    c TEXT;
    f TEXT;
    v_missing TEXT := '';
    v_required_tables TEXT[] := ARRAY[
        'users','xera_wallets','xera_transactions','xera_mining_sessions','xera_daily_claims',
        'xera_allocations','xera_mining_entitlement_state','xera_mining_allocation_state',
        'xera_onchain_claims','xera_hashrate_sessions','xera_hashrate_payments','xera_referrals',
        'xera_launch_config','xera_launch_state','xera_early_miner_bonuses',
        'xera_miner_agreement_acceptances','xera_daily_config'];
    v_required_cols TEXT[] := ARRAY[
        'xera_wallets.cached_balance','xera_wallets.status','xera_wallets.user_id',
        'xera_transactions.wallet_id','xera_transactions.type','xera_transactions.direction',
        'xera_mining_sessions.status','xera_mining_sessions.expires_at',
        'xera_daily_claims.last_claim_date','xera_daily_claims.streak','xera_daily_claims.total_claims',
        'xera_allocations.mining_distributed','xera_allocations.mining_allocation','xera_allocations.total_target',
        'xera_mining_entitlement_state.reserved_amount','xera_mining_entitlement_state.closure_threshold',
        'xera_mining_entitlement_state.free_mining_closed',
        'xera_hashrate_sessions.reserved_entitlement','xera_hashrate_sessions.rewarded_amount',
        'xera_hashrate_sessions.status'];
    v_required_funcs TEXT[] := ARRAY[
        'xera_start_mining_launch','xera_accept_miner_agreement','xera_launch_reconcile',
        'xera_claim_mining_reward','xera_claim_daily_reward'];
    v_required_constraints TEXT[] := ARRAY[
        'xera_mining_distributed_within_allocation','xera_mining_distributed_non_negative'];
    v_required_indexes TEXT[] := ARRAY[
        'xera_one_active_session_per_user','xera_tx_mining_reward_unique','xera_tx_daily_claim_unique',
        'xera_tx_early_bonus_unique'];
BEGIN
    FOREACH t IN ARRAY v_required_tables LOOP
        IF to_regclass('public.' || t) IS NULL THEN v_missing := v_missing || ' table:' || t; END IF;
    END LOOP;
    FOREACH c IN ARRAY v_required_cols LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema='public' AND table_name = split_part(c,'.',1)
                          AND column_name = split_part(c,'.',2)) THEN
            v_missing := v_missing || ' column:' || c;
        END IF;
    END LOOP;
    FOREACH f IN ARRAY v_required_funcs LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                        WHERE n.nspname='public' AND p.proname = f) THEN
            v_missing := v_missing || ' function:' || f;
        END IF;
    END LOOP;
    FOREACH c IN ARRAY v_required_constraints LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c) THEN
            v_missing := v_missing || ' constraint:' || c;
        END IF;
    END LOOP;
    FOREACH c IN ARRAY v_required_indexes LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname = c) THEN
            v_missing := v_missing || ' index:' || c;
        END IF;
    END LOOP;

    IF v_missing <> '' THEN
        RAISE EXCEPTION 'Schema precondition failed — missing:%. Apply all migrations (including 20261021_xera_official_launch_v1.sql) and retry. Nothing was changed.', v_missing;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM xera_allocations WHERE id = 1)
       OR NOT EXISTS (SELECT 1 FROM xera_mining_entitlement_state WHERE id = 1)
       OR NOT EXISTS (SELECT 1 FROM xera_launch_state WHERE id = 1)
       OR NOT EXISTS (SELECT 1 FROM xera_launch_config WHERE id = 1)
       OR NOT EXISTS (SELECT 1 FROM xera_daily_config WHERE id = 1) THEN
        RAISE EXCEPTION 'A required singleton row (allocations / entitlement / launch / daily config) is missing. Nothing was changed.';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- STEP 3 — safety preconditions on the data
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_alloc xera_allocations;
BEGIN
    IF to_regnamespace('xera_backup_launch_reset') IS NOT NULL THEN
        RAISE EXCEPTION 'Schema xera_backup_launch_reset already exists: this reset has been run before. Refusing to run twice. Nothing was changed.';
    END IF;

    SELECT * INTO v_alloc FROM xera_allocations WHERE id = 1;
    IF v_alloc.total_target <> 500000000 OR v_alloc.mining_allocation <> 75000000 THEN
        RAISE EXCEPTION 'Unexpected supply/allocation (total %, mining %). Expected 500000000 / 75000000. Nothing was changed.',
            v_alloc.total_target, v_alloc.mining_allocation;
    END IF;

    -- A reset must never delete real launch bonuses.
    IF EXISTS (SELECT 1 FROM xera_early_miner_bonuses)
       OR (SELECT bonus_slots_used FROM xera_launch_state WHERE id = 1) <> 0
       OR (SELECT bonus_distributed FROM xera_launch_state WHERE id = 1) <> 0 THEN
        RAISE EXCEPTION 'Early-miner bonuses already exist: the official launch has started. Refusing to reset. Nothing was changed.';
    END IF;

    IF EXISTS (SELECT 1 FROM xera_onchain_claims)
       OR (SELECT global_reserved_amount FROM xera_mining_allocation_state WHERE id = 1) <> 0 THEN
        RAISE EXCEPTION 'xera_onchain_claims has rows (or the on-chain counter is non-zero). Resolve these first — see header. Nothing was changed.';
    END IF;
END $$;

-- Freeze XERA activity for the duration of this transaction (fails safe on timeout).
LOCK TABLE xera_launch_state, xera_mining_entitlement_state, xera_allocations,
           xera_wallets, xera_transactions, xera_mining_sessions, xera_daily_claims,
           xera_hashrate_sessions
    IN ACCESS EXCLUSIVE MODE;

-- ---------------------------------------------------------------------------
-- STEP 4 — backups (private schema, no API exposure)
-- ---------------------------------------------------------------------------
CREATE SCHEMA xera_backup_launch_reset;
REVOKE ALL ON SCHEMA xera_backup_launch_reset FROM PUBLIC, anon, authenticated;

CREATE TABLE xera_backup_launch_reset.xera_wallets                  AS TABLE public.xera_wallets;
CREATE TABLE xera_backup_launch_reset.xera_transactions             AS TABLE public.xera_transactions;
CREATE TABLE xera_backup_launch_reset.xera_mining_sessions          AS TABLE public.xera_mining_sessions;
CREATE TABLE xera_backup_launch_reset.xera_daily_claims             AS TABLE public.xera_daily_claims;
CREATE TABLE xera_backup_launch_reset.xera_allocations              AS TABLE public.xera_allocations;
CREATE TABLE xera_backup_launch_reset.xera_mining_entitlement_state AS TABLE public.xera_mining_entitlement_state;
CREATE TABLE xera_backup_launch_reset.xera_mining_allocation_state  AS TABLE public.xera_mining_allocation_state;
CREATE TABLE xera_backup_launch_reset.xera_hashrate_sessions        AS TABLE public.xera_hashrate_sessions;
CREATE TABLE xera_backup_launch_reset.xera_hashrate_payments        AS TABLE public.xera_hashrate_payments;
CREATE TABLE xera_backup_launch_reset.xera_referrals                AS TABLE public.xera_referrals;

CREATE TABLE xera_backup_launch_reset.backup_meta (
    taken_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    wallets            BIGINT,
    wallet_balance_sum NUMERIC,
    transactions       BIGINT,
    sessions           BIGINT,
    daily_claims       BIGINT,
    mining_distributed NUMERIC,
    reserved_amount    NUMERIC
);
INSERT INTO xera_backup_launch_reset.backup_meta
SELECT now(),
       (SELECT COUNT(*) FROM public.xera_wallets),
       (SELECT COALESCE(SUM(cached_balance),0) FROM public.xera_wallets),
       (SELECT COUNT(*) FROM public.xera_transactions),
       (SELECT COUNT(*) FROM public.xera_mining_sessions),
       (SELECT COUNT(*) FROM public.xera_daily_claims),
       (SELECT mining_distributed FROM public.xera_allocations WHERE id = 1),
       (SELECT reserved_amount FROM public.xera_mining_entitlement_state WHERE id = 1);

DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'xera_backup_launch_reset' LOOP
        EXECUTE format('ALTER TABLE xera_backup_launch_reset.%I ENABLE ROW LEVEL SECURITY', r.tablename);
        EXECUTE format('REVOKE ALL ON xera_backup_launch_reset.%I FROM PUBLIC, anon, authenticated', r.tablename);
    END LOOP;
    -- Backups must match the live tables exactly before anything is deleted.
    IF (SELECT COUNT(*) FROM xera_backup_launch_reset.xera_transactions) <> (SELECT COUNT(*) FROM public.xera_transactions)
       OR (SELECT COUNT(*) FROM xera_backup_launch_reset.xera_wallets) <> (SELECT COUNT(*) FROM public.xera_wallets)
       OR (SELECT COUNT(*) FROM xera_backup_launch_reset.xera_mining_sessions) <> (SELECT COUNT(*) FROM public.xera_mining_sessions) THEN
        RAISE EXCEPTION 'Backup row counts do not match the live tables. Nothing was changed.';
    END IF;
END $$;

-- Values the post-reset verification compares against.
CREATE TEMP TABLE xera_reset_before ON COMMIT DROP AS
SELECT (SELECT COUNT(*) FROM public.users)                                     AS users,
       (SELECT COUNT(*) FROM public.xera_wallets)                              AS wallets,
       (SELECT string_agg(id::text || ':' || user_id::text || ':' || status, ',' ORDER BY id) FROM public.xera_wallets) AS wallet_identity,
       (SELECT total_target FROM public.xera_allocations WHERE id = 1)         AS total_target,
       (SELECT mining_allocation FROM public.xera_allocations WHERE id = 1)    AS mining_allocation,
       (SELECT COUNT(*) FROM public.xera_hashrate_sessions)                    AS hashrate_sessions,
       (SELECT COUNT(*) FROM public.xera_hashrate_payments)                    AS hashrate_payments,
       (SELECT COUNT(*) FROM public.xera_daily_claims)                         AS daily_claim_rows;

-- ---------------------------------------------------------------------------
-- STEP 5 — the reset
-- ---------------------------------------------------------------------------
DELETE FROM public.xera_transactions    WHERE true;
DELETE FROM public.xera_mining_sessions WHERE true;

UPDATE public.xera_wallets
   SET cached_balance = 0, updated_at = now()
 WHERE true;

UPDATE public.xera_daily_claims
   SET last_claim_date = NULL, streak = 0, total_claims = 0, updated_at = now()
 WHERE true;

UPDATE public.xera_allocations
   SET mining_distributed = 0, updated_at = now()
 WHERE id = 1;

-- Capacity still held by paid hashrate sessions stays reserved (see header).
UPDATE public.xera_mining_entitlement_state e
   SET reserved_amount = h.held,
       free_mining_closed = (h.held >= e.closure_threshold),
       updated_at = now()
  FROM (SELECT COALESCE(SUM(GREATEST(reserved_entitlement - rewarded_amount, 0)), 0) AS held
          FROM public.xera_hashrate_sessions
         WHERE status IN ('PENDING_PAYMENT', 'ACTIVE')) h
 WHERE e.id = 1;

-- ---------------------------------------------------------------------------
-- STEP 6 — verification (any failure rolls EVERYTHING back)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    b xera_reset_before;
    v_held NUMERIC;
    v_rec JSONB;
BEGIN
    SELECT * INTO b FROM xera_reset_before;

    IF (SELECT COUNT(*) FROM xera_transactions) <> 0 THEN RAISE EXCEPTION 'Verify failed: transactions remain'; END IF;
    IF (SELECT COUNT(*) FROM xera_mining_sessions) <> 0 THEN RAISE EXCEPTION 'Verify failed: sessions remain'; END IF;
    IF (SELECT COALESCE(SUM(cached_balance),0) FROM xera_wallets) <> 0 THEN RAISE EXCEPTION 'Verify failed: wallet balances not zero'; END IF;
    IF EXISTS (SELECT 1 FROM xera_daily_claims WHERE last_claim_date IS NOT NULL OR streak <> 0 OR total_claims <> 0) THEN
        RAISE EXCEPTION 'Verify failed: daily-claim progress not cleared'; END IF;
    IF (SELECT mining_distributed FROM xera_allocations WHERE id = 1) <> 0 THEN RAISE EXCEPTION 'Verify failed: mining_distributed not zero'; END IF;

    IF (SELECT COUNT(*) FROM users) <> b.users THEN RAISE EXCEPTION 'Verify failed: user count changed'; END IF;
    IF (SELECT COUNT(*) FROM xera_wallets) <> b.wallets THEN RAISE EXCEPTION 'Verify failed: wallet count changed'; END IF;
    IF (SELECT string_agg(id::text || ':' || user_id::text || ':' || status, ',' ORDER BY id) FROM xera_wallets)
         IS DISTINCT FROM b.wallet_identity THEN RAISE EXCEPTION 'Verify failed: wallet identity/status changed'; END IF;
    IF (SELECT total_target FROM xera_allocations WHERE id = 1) <> b.total_target
       OR (SELECT mining_allocation FROM xera_allocations WHERE id = 1) <> b.mining_allocation THEN
        RAISE EXCEPTION 'Verify failed: supply or mining allocation changed'; END IF;
    IF (SELECT COUNT(*) FROM xera_hashrate_sessions) <> b.hashrate_sessions
       OR (SELECT COUNT(*) FROM xera_hashrate_payments) <> b.hashrate_payments
       OR (SELECT COUNT(*) FROM xera_daily_claims) <> b.daily_claim_rows THEN
        RAISE EXCEPTION 'Verify failed: preserved tables changed row count'; END IF;

    SELECT COALESCE(SUM(GREATEST(reserved_entitlement - rewarded_amount, 0)), 0) INTO v_held
      FROM xera_hashrate_sessions WHERE status IN ('PENDING_PAYMENT','ACTIVE');
    IF (SELECT reserved_amount FROM xera_mining_entitlement_state WHERE id = 1) <> v_held THEN
        RAISE EXCEPTION 'Verify failed: entitlement ledger not re-based correctly'; END IF;

    v_rec := xera_launch_reconcile();
    IF NOT (v_rec->>'ok')::boolean THEN
        RAISE EXCEPTION 'Verify failed: reconciliation reports problems: %', v_rec->'problems';
    END IF;
END $$;

COMMIT;

-- ---------------------------------------------------------------------------
-- RESULT SUMMARY (read-only)
-- ---------------------------------------------------------------------------
SELECT 'backup taken at'            AS item, taken_at::text AS value FROM xera_backup_launch_reset.backup_meta
UNION ALL SELECT 'backed-up wallets',        wallets::text FROM xera_backup_launch_reset.backup_meta
UNION ALL SELECT 'backed-up balance total',  wallet_balance_sum::text FROM xera_backup_launch_reset.backup_meta
UNION ALL SELECT 'backed-up transactions',   transactions::text FROM xera_backup_launch_reset.backup_meta
UNION ALL SELECT 'backed-up sessions',       sessions::text FROM xera_backup_launch_reset.backup_meta
UNION ALL SELECT 'live wallets (kept)',      COUNT(*)::text FROM public.xera_wallets
UNION ALL SELECT 'live balance total',       COALESCE(SUM(cached_balance),0)::text FROM public.xera_wallets
UNION ALL SELECT 'live transactions',        COUNT(*)::text FROM public.xera_transactions
UNION ALL SELECT 'mining_distributed',       mining_distributed::text FROM public.xera_allocations WHERE id = 1
UNION ALL SELECT 'mining_allocation',        mining_allocation::text FROM public.xera_allocations WHERE id = 1
UNION ALL SELECT 'total_target',             total_target::text FROM public.xera_allocations WHERE id = 1
UNION ALL SELECT 'entitlement reserved (paid hashrate only)', reserved_amount::text FROM public.xera_mining_entitlement_state WHERE id = 1;
