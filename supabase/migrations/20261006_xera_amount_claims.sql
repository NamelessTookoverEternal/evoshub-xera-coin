-- ============================================================
-- XERA — AMOUNT-BASED ON-CHAIN CLAIMS  +  DAILY CLAIM INSIDE THE 75M POOL
-- ============================================================
-- Two product decisions, implemented together because they depend on each other:
--
--   1. The DAILY CLAIM reward is real XERA: it is counted against the same
--      75,000,000 mining pool as free mining and hashrate, and it can be moved
--      on-chain like any other mining reward.
--
--   2. On-chain claims are AMOUNT-BASED. The user types how much of their
--      claimable balance to move to their wallet. The app debits that amount
--      from the in-app balance and the contract splits it 25% transferable /
--      75% locked in vesting (the split is enforced on-chain by the
--      distributor; the database only records it).
--
-- WHAT COUNTS AS "CLAIMABLE"
--   eligible credits  = MINING_REWARD + DAILY_CLAIM (CONFIRMED credits). Only
--                       these are funded from the mining pool the distributor
--                       contract holds. Purchases, referral rewards, bonuses and
--                       admin credits are NOT claimable on-chain.
--   already moved     = every row in xera_onchain_claims for the user, in ANY
--                       status. FAILED / EXPIRED rows stay counted on purpose:
--                       they are re-signed through xera_retry_onchain_claim
--                       (same reference_id => at most ONE on-chain execution),
--                       so their funds remain held until they settle.
--   claimable         = LEAST(in-app balance, eligible credits - already moved)
--
-- Nothing in the contracts changes: the distributor already takes an amount and
-- a single-use reference id, and already performs the 25/75 split.
--
-- Safe to re-run: every statement is idempotent.
-- ============================================================

-- ------------------------------------------------------------
-- 1. LEDGER: a debit type for moving balance on-chain
-- ------------------------------------------------------------
ALTER TABLE xera_transactions DROP CONSTRAINT IF EXISTS xera_transactions_type_check;
ALTER TABLE xera_transactions ADD CONSTRAINT xera_transactions_type_check CHECK (type IN (
    'MINING_REWARD','XERA_PURCHASE','REFERRAL_REWARD','BONUS','DAILY_CLAIM',
    'ADMIN_CREDIT','ADMIN_DEBIT','REVERSAL','MIGRATION','ONCHAIN_CLAIM'
));

-- One ledger debit per on-chain claim reference (idempotency backstop).
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_onchain_claim_unique
    ON xera_transactions (reference_id)
    WHERE type = 'ONCHAIN_CLAIM';

-- How much of the in-app balance this claim debited. 0 for claims created before
-- this migration (they never debited the balance; the claimable formula above
-- still subtracts them, so nothing can be claimed twice).
ALTER TABLE xera_onchain_claims
    ADD COLUMN IF NOT EXISTS balance_debited NUMERIC(20,4) NOT NULL DEFAULT 0;

-- ------------------------------------------------------------
-- 2. CLAIMABLE BALANCE (read-only; also used inside the reservation)
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION xera_claimable_balance(
    p_user_id BIGINT
) RETURNS TABLE(cached_balance NUMERIC, eligible_total NUMERIC, onchain_total NUMERIC, claimable NUMERIC)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_cached  NUMERIC;
    v_elig    NUMERIC;
    v_onchain NUMERIC;
BEGIN
    SELECT w.cached_balance INTO v_cached FROM xera_wallets w WHERE w.user_id = p_user_id;

    SELECT COALESCE(SUM(t.amount), 0) INTO v_elig
        FROM xera_transactions t
        WHERE t.user_id = p_user_id
          AND t.direction = 'CREDIT'
          AND t.status = 'CONFIRMED'
          AND t.type IN ('MINING_REWARD', 'DAILY_CLAIM');

    SELECT COALESCE(SUM(c.claimed_amount), 0) INTO v_onchain
        FROM xera_onchain_claims c
        WHERE c.user_id = p_user_id;

    cached_balance := COALESCE(v_cached, 0);
    eligible_total := v_elig;
    onchain_total  := v_onchain;
    claimable      := GREATEST(0, LEAST(COALESCE(v_cached, 0), v_elig - v_onchain));
    RETURN NEXT;
END;
$$;

-- ------------------------------------------------------------
-- 3. RESERVE AN AMOUNT-BASED CLAIM (atomic)
-- ------------------------------------------------------------
-- One Postgres transaction: lock the on-chain allocation row, lock the wallet,
-- verify the amount against the claimable balance, then record the claim, the
-- ledger debit, the balance debit and the global reservation together. If any
-- step fails, none of it happens.
--
-- Lock order: xera_mining_allocation_state -> xera_wallets. The wallet is always
-- the LAST lock taken anywhere in the XERA schema, so this cannot deadlock with
-- mining claims, daily claims or hashrate credits.
CREATE OR REPLACE FUNCTION xera_reserve_onchain_claim_amount(
    p_reference_id        TEXT,
    p_user_id             BIGINT,
    p_chain               TEXT,
    p_wallet_address      TEXT,
    p_amount              NUMERIC,
    p_transferable_amount NUMERIC,
    p_locked_amount       NUMERIC,
    p_contract_address    TEXT,
    p_deadline            TIMESTAMPTZ
) RETURNS xera_onchain_claims
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_state  xera_mining_allocation_state;
    v_wallet xera_wallets;
    v_bal    RECORD;
    v_row    xera_onchain_claims;
BEGIN
    IF p_chain NOT IN ('BNB', 'TON') THEN
        RAISE EXCEPTION 'invalid_chain' USING ERRCODE = 'P0101';
    END IF;
    IF p_amount IS NULL OR p_amount <= 0 THEN
        RAISE EXCEPTION 'invalid_amount' USING ERRCODE = 'P0109';
    END IF;
    IF p_transferable_amount < 0 OR p_locked_amount < 0 OR p_transferable_amount + p_locked_amount <> p_amount THEN
        RAISE EXCEPTION 'invalid_split' USING ERRCODE = 'P0140';
    END IF;

    SELECT * INTO v_state FROM xera_mining_allocation_state WHERE id = 1 FOR UPDATE;

    SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet_not_found' USING ERRCODE = 'P0007';
    END IF;
    IF v_wallet.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'wallet_not_active' USING ERRCODE = 'P0001';
    END IF;

    SELECT * INTO v_bal FROM xera_claimable_balance(p_user_id);
    IF p_amount > v_bal.claimable THEN
        RAISE EXCEPTION 'insufficient_claimable_balance' USING ERRCODE = 'P0141';
    END IF;

    IF v_state.global_reserved_amount + p_amount > v_state.global_cap THEN
        RAISE EXCEPTION 'global_mining_allocation_exceeded' USING ERRCODE = 'P0111';
    END IF;

    BEGIN
        INSERT INTO xera_onchain_claims (
            reference_id, user_id, chain, wallet_address,
            claimed_amount, transferable_amount, locked_amount,
            contract_address, signature_deadline, status, balance_debited
        ) VALUES (
            p_reference_id, p_user_id, p_chain, p_wallet_address,
            p_amount, p_transferable_amount, p_locked_amount,
            p_contract_address, p_deadline, 'SIGNED', p_amount
        )
        RETURNING * INTO v_row;
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'reference_already_reserved' USING ERRCODE = 'P0102';
    END;

    INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
    VALUES (v_wallet.id, p_user_id, 'ONCHAIN_CLAIM', p_amount, 'DEBIT', p_reference_id,
            jsonb_build_object('chain', p_chain, 'wallet_address', p_wallet_address,
                               'transferable', p_transferable_amount, 'locked', p_locked_amount));

    UPDATE xera_wallets
        SET cached_balance = cached_balance - p_amount, updated_at = now()
        WHERE id = v_wallet.id;

    UPDATE xera_mining_allocation_state
        SET global_reserved_amount = global_reserved_amount + p_amount, updated_at = now()
        WHERE id = 1;

    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 4. DAILY CLAIM COUNTS AGAINST THE 75M POOL
-- ------------------------------------------------------------
-- Same shape as before (signature unchanged), plus the pool accounting that
-- xera_claim_mining_reward performs, in the SAME lock order:
--   entitlement ledger -> legacy allocations -> wallet.
-- The daily reward follows the free-mining closure rule: once the pool reaches
-- the closure threshold, free rewards stop so the remainder stays available for
-- hashrate sessions that were already paid for.
CREATE OR REPLACE FUNCTION xera_claim_daily_reward(
    p_user_id BIGINT,
    p_reward  NUMERIC
) RETURNS TABLE(new_balance NUMERIC, reward_credited NUMERIC, streak INTEGER)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_state     xera_mining_entitlement_state;
    v_alloc     xera_allocations;
    v_wallet    xera_wallets;
    v_claim     xera_daily_claims;
    v_today     DATE := now()::date;
    v_streak    INTEGER;
BEGIN
    SELECT * INTO v_state FROM xera_mining_entitlement_state WHERE id = 1 FOR UPDATE;
    SELECT * INTO v_alloc FROM xera_allocations WHERE id = 1 FOR UPDATE;

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

    IF v_state.free_mining_closed OR v_state.reserved_amount >= v_state.closure_threshold THEN
        RAISE EXCEPTION 'free_mining_closed' USING ERRCODE = 'P0203';
    END IF;
    IF v_state.reserved_amount + p_reward > v_state.cap
       OR v_alloc.mining_distributed + p_reward > v_alloc.mining_allocation THEN
        RAISE EXCEPTION 'allocation_exhausted' USING ERRCODE = 'P0006';
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

    UPDATE xera_allocations
        SET mining_distributed = mining_distributed + p_reward, updated_at = now()
        WHERE id = 1;

    UPDATE xera_mining_entitlement_state
        SET reserved_amount = reserved_amount + p_reward,
            free_mining_closed = free_mining_closed OR (reserved_amount + p_reward >= closure_threshold),
            updated_at = now()
        WHERE id = 1;

    UPDATE xera_daily_claims
        SET last_claim_date = v_today, streak = v_streak, total_claims = v_claim.total_claims + 1, updated_at = now()
        WHERE user_id = p_user_id;

    reward_credited := p_reward;
    streak := v_streak;
    RETURN NEXT;
END;
$$;

-- ------------------------------------------------------------
-- 4b. CONFIRMING A CLAIM THAT ALREADY EXPIRED / FAILED
-- ------------------------------------------------------------
-- Expiring or failing a claim releases its slice of the global on-chain total.
-- If the user's transaction nevertheless landed before the signature deadline
-- and is confirmed later, those tokens really did leave the distributor, so the
-- slice must be counted again. Without this the global total would drift low by
-- the claimed amount each time that happens. Unchanged otherwise.
CREATE OR REPLACE FUNCTION xera_confirm_onchain_claim(
    p_reference_id     TEXT,
    p_transaction_hash TEXT,
    p_block_number     BIGINT
) RETURNS xera_onchain_claims
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row         xera_onchain_claims;
    v_prev_status TEXT;
BEGIN
    SELECT * INTO v_row FROM xera_onchain_claims WHERE reference_id = p_reference_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'claim_not_found' USING ERRCODE = 'P0103';
    END IF;

    IF v_row.status = 'CONFIRMED' THEN
        RETURN v_row; -- idempotent: confirming twice with the same data is a no-op, not an error
    END IF;

    v_prev_status := v_row.status;

    UPDATE xera_onchain_claims
        SET status = 'CONFIRMED',
            transaction_hash = p_transaction_hash,
            block_number = p_block_number,
            confirmed_at = now(),
            updated_at = now()
        WHERE reference_id = p_reference_id
        RETURNING * INTO v_row;

    IF v_prev_status IN ('FAILED', 'EXPIRED') THEN
        UPDATE xera_mining_allocation_state
            SET global_reserved_amount = global_reserved_amount + v_row.claimed_amount, updated_at = now()
            WHERE id = 1;
    END IF;

    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 5. ONE-TIME BACKFILL: daily rewards paid out BEFORE this migration
-- ------------------------------------------------------------
-- Those rewards were never counted against the pool. Count them once. The marker
-- row makes re-running this file harmless (it would otherwise double-count).
CREATE TABLE IF NOT EXISTS xera_pool_backfill_markers (
    name       TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
DECLARE
    v_total NUMERIC;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM xera_pool_backfill_markers WHERE name = 'daily_claims_into_pool') THEN
        SELECT COALESCE(SUM(amount), 0) INTO v_total
            FROM xera_transactions WHERE type = 'DAILY_CLAIM' AND direction = 'CREDIT';

        IF v_total > 0 THEN
            UPDATE xera_mining_entitlement_state
                SET reserved_amount = reserved_amount + v_total,
                    free_mining_closed = free_mining_closed OR (reserved_amount + v_total >= closure_threshold),
                    updated_at = now()
                WHERE id = 1;
            UPDATE xera_allocations
                SET mining_distributed = mining_distributed + v_total, updated_at = now()
                WHERE id = 1;
        END IF;

        INSERT INTO xera_pool_backfill_markers (name) VALUES ('daily_claims_into_pool');
    END IF;
END;
$$;

-- ------------------------------------------------------------
-- 6. PRIVILEGES — same default-deny posture as the rest of the XERA schema
-- ------------------------------------------------------------
ALTER TABLE xera_pool_backfill_markers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON xera_pool_backfill_markers FROM PUBLIC;
GRANT SELECT, INSERT ON xera_pool_backfill_markers TO service_role;

REVOKE EXECUTE ON FUNCTION xera_claimable_balance(BIGINT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_reserve_onchain_claim_amount(TEXT, BIGINT, TEXT, TEXT, NUMERIC, NUMERIC, NUMERIC, TEXT, TIMESTAMPTZ) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_claim_daily_reward(BIGINT, NUMERIC) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_confirm_onchain_claim(TEXT, TEXT, BIGINT) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION xera_claimable_balance(BIGINT) TO service_role;
GRANT  EXECUTE ON FUNCTION xera_reserve_onchain_claim_amount(TEXT, BIGINT, TEXT, TEXT, NUMERIC, NUMERIC, NUMERIC, TEXT, TIMESTAMPTZ) TO service_role;
GRANT  EXECUTE ON FUNCTION xera_claim_daily_reward(BIGINT, NUMERIC) TO service_role;
GRANT  EXECUTE ON FUNCTION xera_confirm_onchain_claim(TEXT, TEXT, BIGINT) TO service_role;
