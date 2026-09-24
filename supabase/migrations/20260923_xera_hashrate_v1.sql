-- ============================================================
-- XERA HASHRATE SYSTEM — pre-testnet implementation
--
-- Additive/CREATE OR REPLACE only. Nothing from 20260901_xera_token_v1.sql,
-- 20260912_xera_blockchain_v1.sql or 20260914_xera_blockchain_hardening.sql
-- is dropped, renamed, or reinterpreted. Existing rows are preserved.
--
-- ------------------------------------------------------------
-- ARCHITECTURE NOTE — read before touching any of this file
-- ------------------------------------------------------------
-- The task brief for this feature instructed reusing a table called
-- `xera_mining_allocation_state` as "the single canonical global mining
-- allocation ledger" for BOTH free mining and hashrate. That table
-- already exists (20260914_xera_blockchain_hardening.sql) and its
-- `global_reserved_amount` column already has a different, live meaning:
-- the total amount *claimed on-chain* (BNB+TON combined, via
-- xera_reserve_onchain_claim / claims.py). That is a strict SUBSET of
-- total off-chain mining entitlement — a user can be sitting on a mining
-- balance that was never claimed on-chain at all. Repurposing that same
-- counter for "total off-chain entitlement ever created" would silently
-- change what the 65M/70M thresholds and the on-chain 75M cap each mean,
-- and would be exactly the kind of redesign-by-accident this task
-- explicitly forbids ("DO NOT modify working blockchain contracts
-- unnecessarily", "DO NOT break the existing ... BNB Testnet
-- architecture").
--
-- xera_mining_allocation_state (on-chain claims) is therefore left
-- completely untouched by this migration.
--
-- Instead, a NEW singleton table — xera_mining_entitlement_state — is
-- introduced as the canonical ledger for total off-chain mining
-- entitlement (free mining + hashrate), which is what section 12/13/18
-- of the brief and the 65M/70M rules actually describe. It is seeded
-- from today's xera_allocations.mining_distributed so it starts in sync.
-- xera_allocations.mining_distributed is kept exactly as before (nothing
-- removed) and continues to update in the same transaction as free-mining
-- claims — it becomes a derived/legacy reporting mirror, per the
-- "don't delete, treat as legacy" instruction, rather than an
-- independent cap. This decision should be reviewed by a human before
-- mainnet, per section 4 of the architecture-decisions brief.
-- ============================================================

-- ------------------------------------------------------------
-- 1. CANONICAL OFF-CHAIN MINING ENTITLEMENT LEDGER
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_mining_entitlement_state (
    id                   SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    reserved_amount      NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK (reserved_amount >= 0),
    cap                  NUMERIC(20,4) NOT NULL DEFAULT 75000000,
    warning_threshold    NUMERIC(20,4) NOT NULL DEFAULT 65000000,
    closure_threshold    NUMERIC(20,4) NOT NULL DEFAULT 70000000,
    free_mining_closed   BOOLEAN NOT NULL DEFAULT false,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT xera_entitlement_reserved_within_cap CHECK (reserved_amount <= cap)
);

INSERT INTO xera_mining_entitlement_state (id, reserved_amount)
SELECT 1, COALESCE(mining_distributed, 0) FROM xera_allocations WHERE id = 1
ON CONFLICT (id) DO NOTHING;
-- Fallback if xera_allocations somehow has no row yet.
INSERT INTO xera_mining_entitlement_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ---- atomic reserve / release on the canonical ledger ---------------
-- Used directly by hashrate purchase/release below, and inlined (same
-- lock, same transaction) into xera_claim_mining_reward further down so
-- free mining and hashrate share one lock and one cap.

CREATE OR REPLACE FUNCTION xera_reserve_mining_entitlement(
    p_amount NUMERIC,
    p_source TEXT DEFAULT 'UNSPECIFIED'
) RETURNS xera_mining_entitlement_state
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_state xera_mining_entitlement_state;
BEGIN
    IF p_amount <= 0 THEN
        RAISE EXCEPTION 'invalid_amount' USING ERRCODE = 'P0201';
    END IF;

    SELECT * INTO v_state FROM xera_mining_entitlement_state WHERE id = 1 FOR UPDATE;

    IF v_state.reserved_amount + p_amount > v_state.cap THEN
        RAISE EXCEPTION 'entitlement_cap_exceeded' USING ERRCODE = 'P0202';
    END IF;

    UPDATE xera_mining_entitlement_state
        SET reserved_amount = reserved_amount + p_amount,
            free_mining_closed = free_mining_closed OR (reserved_amount + p_amount >= closure_threshold),
            updated_at = now()
        WHERE id = 1
        RETURNING * INTO v_state;

    RETURN v_state;
END;
$$;

CREATE OR REPLACE FUNCTION xera_release_mining_entitlement(
    p_amount NUMERIC
) RETURNS xera_mining_entitlement_state
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_state xera_mining_entitlement_state;
BEGIN
    IF p_amount <= 0 THEN
        RAISE EXCEPTION 'invalid_amount' USING ERRCODE = 'P0201';
    END IF;

    UPDATE xera_mining_entitlement_state
        SET reserved_amount = GREATEST(0, reserved_amount - p_amount), updated_at = now()
        WHERE id = 1
        RETURNING * INTO v_state;

    RETURN v_state;
END;
$$;

-- ---- fold the canonical ledger into the existing free-mining claim --
-- Additive change to the existing function (same signature, same
-- return shape — callers in mining.py are untouched). New behavior:
-- the reward is now ALSO clamped by remaining canonical capacity (not
-- just legacy xera_allocations capacity), and the canonical ledger is
-- incremented in the SAME transaction as the legacy mining_distributed
-- counter, so the two can never drift apart from this point forward.
-- Lock order (entitlement_state, then xera_allocations, then wallet) is
-- kept identical to xera_reserve_hashrate below to avoid deadlocks
-- between concurrent free-mining claims and hashrate purchases.
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
    v_state     xera_mining_entitlement_state;
    v_wallet    xera_wallets;
    v_reward    NUMERIC(20,4);
    v_remaining NUMERIC(20,4);
    v_remaining_canonical NUMERIC(20,4);
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

    -- Canonical ledger locked first (consistent global lock order with
    -- xera_reserve_hashrate), then the legacy allocations row.
    SELECT * INTO v_state FROM xera_mining_entitlement_state WHERE id = 1 FOR UPDATE;
    SELECT * INTO v_alloc FROM xera_allocations WHERE id = 1 FOR UPDATE;

    v_remaining := v_alloc.mining_allocation - v_alloc.mining_distributed;
    v_remaining_canonical := v_state.cap - v_state.reserved_amount;

    v_reward := LEAST(v_session.estimated_reward, GREATEST(v_remaining, 0), GREATEST(v_remaining_canonical, 0));
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

    UPDATE xera_mining_entitlement_state
        SET reserved_amount = reserved_amount + v_reward,
            free_mining_closed = free_mining_closed OR (reserved_amount + v_reward >= closure_threshold),
            updated_at = now()
        WHERE id = 1;

    UPDATE xera_mining_sessions
        SET status = 'CLAIMED', claimed_at = now(), estimated_reward = v_reward
        WHERE id = p_session_id;

    reward_credited := v_reward;
    RETURN NEXT;
END;
$$;

-- ---- fold free-mining closure into session start ---------------------
-- Additive: same signature/return shape as before. New behavior: once
-- the canonical ledger has crossed the 70M closure threshold, no new
-- free-mining session may start (section 13). Hashrate purchases are
-- NOT gated by this function — see xera_reserve_hashrate.
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
    v_state     xera_mining_entitlement_state;
BEGIN
    SELECT * INTO v_state FROM xera_mining_entitlement_state WHERE id = 1;
    IF v_state.free_mining_closed OR v_state.reserved_amount >= v_state.closure_threshold THEN
        RAISE EXCEPTION 'free_mining_closed' USING ERRCODE = 'P0203';
    END IF;

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

-- ------------------------------------------------------------
-- 2. HASHRATE TIERS (admin-configurable — never hard-coded in app code)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_hashrate_tiers (
    id                  BIGSERIAL PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    price               NUMERIC(12,2) NOT NULL CHECK (price > 0),
    currency            TEXT NOT NULL DEFAULT 'GHS',
    duration_days       INTEGER NOT NULL DEFAULT 30 CHECK (duration_days > 0),
    daily_rate          NUMERIC(20,4) NOT NULL CHECK (daily_rate > 0),
    maximum_entitlement NUMERIC(20,4) GENERATED ALWAYS AS (daily_rate * duration_days) STORED,
    enabled             BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by          BIGINT REFERENCES users(id)
);

-- Planning baseline from the brief — admin can retune price/rate later;
-- nothing in application code hard-codes these numbers.
INSERT INTO xera_hashrate_tiers (name, price, currency, duration_days, daily_rate)
VALUES
    ('starter', 1, 'GHS', 30, 5),
    ('boost',   2, 'GHS', 30, 12)
ON CONFLICT (name) DO NOTHING;

-- ------------------------------------------------------------
-- 3. HASHRATE SESSIONS
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_hashrate_sessions (
    id                    BIGSERIAL PRIMARY KEY,
    user_id               BIGINT NOT NULL REFERENCES users(id),
    tier_id               BIGINT NOT NULL REFERENCES xera_hashrate_tiers(id),
    payment_method        TEXT NOT NULL CHECK (payment_method IN ('PAYSTACK', 'CRYPTO')),
    payment_currency      TEXT NOT NULL,
    amount_paid           NUMERIC(12,2) NOT NULL,
    daily_rate            NUMERIC(20,4) NOT NULL,
    duration_days         INTEGER NOT NULL,
    maximum_entitlement   NUMERIC(20,4) NOT NULL,
    reserved_entitlement  NUMERIC(20,4) NOT NULL,
    rewarded_amount       NUMERIC(20,4) NOT NULL DEFAULT 0,
    started_at            TIMESTAMPTZ,
    expires_at            TIMESTAMPTZ,
    status                TEXT NOT NULL DEFAULT 'PENDING_PAYMENT' CHECK (status IN
                              ('PENDING_PAYMENT', 'ACTIVE', 'COMPLETED', 'CANCELLED', 'EXPIRED', 'FAILED', 'FLAGGED')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_xera_hashrate_sessions_user   ON xera_hashrate_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_xera_hashrate_sessions_status ON xera_hashrate_sessions(status);

CREATE TABLE IF NOT EXISTS xera_hashrate_payments (
    id            BIGSERIAL PRIMARY KEY,
    session_id    BIGINT NOT NULL REFERENCES xera_hashrate_sessions(id),
    user_id       BIGINT NOT NULL REFERENCES users(id),
    provider      TEXT NOT NULL CHECK (provider IN ('PAYSTACK', 'CRYPTO')),
    -- XERA-specific reference prefix (see hashrate.py) so these can never
    -- collide with EVOSDATA Paystack references sharing the same Paystack account.
    reference     TEXT NOT NULL UNIQUE,
    amount        NUMERIC(12,2) NOT NULL,
    currency      TEXT NOT NULL,
    asset         TEXT,
    tx_hash       TEXT,
    confirmations INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN
                      ('PENDING', 'CONFIRMED', 'FAILED', 'EXPIRED', 'CANCELLED')),
    raw_webhook   JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_xera_hashrate_payments_session ON xera_hashrate_payments(session_id);
CREATE INDEX IF NOT EXISTS idx_xera_hashrate_payments_user    ON xera_hashrate_payments(user_id);

-- A confirmed crypto tx_hash can never be reused to confirm a second session.
CREATE UNIQUE INDEX IF NOT EXISTS xera_hashrate_payments_txhash_confirmed_unique
    ON xera_hashrate_payments (tx_hash)
    WHERE tx_hash IS NOT NULL AND status = 'CONFIRMED';

-- ---- purchase: reserve full 30-day entitlement, create PENDING rows --
CREATE OR REPLACE FUNCTION xera_purchase_hashrate(
    p_user_id        BIGINT,
    p_tier_id        BIGINT,
    p_payment_method TEXT,
    p_reference      TEXT
) RETURNS TABLE(
    session_id            BIGINT,
    payment_id            BIGINT,
    maximum_entitlement   NUMERIC,
    price                 NUMERIC,
    currency              TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_tier      xera_hashrate_tiers;
    v_entitlement NUMERIC(20,4);
    v_session   xera_hashrate_sessions;
    v_payment   xera_hashrate_payments;
BEGIN
    IF p_payment_method NOT IN ('PAYSTACK', 'CRYPTO') THEN
        RAISE EXCEPTION 'invalid_payment_method' USING ERRCODE = 'P0204';
    END IF;

    SELECT * INTO v_tier FROM xera_hashrate_tiers WHERE id = p_tier_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'tier_not_found' USING ERRCODE = 'P0205';
    END IF;
    IF NOT v_tier.enabled THEN
        RAISE EXCEPTION 'tier_disabled' USING ERRCODE = 'P0206';
    END IF;

    v_entitlement := v_tier.daily_rate * v_tier.duration_days;

    -- Atomic reservation against the SAME canonical pool free mining
    -- claims into (xera_mining_entitlement_state) — raises
    -- entitlement_cap_exceeded if the complete session cannot be
    -- supported. No partial session is ever created.
    PERFORM xera_reserve_mining_entitlement(v_entitlement, 'HASHRATE');

    INSERT INTO xera_hashrate_sessions (
        user_id, tier_id, payment_method, payment_currency, amount_paid,
        daily_rate, duration_days, maximum_entitlement, reserved_entitlement, status
    ) VALUES (
        p_user_id, p_tier_id, p_payment_method, v_tier.currency, v_tier.price,
        v_tier.daily_rate, v_tier.duration_days, v_entitlement, v_entitlement, 'PENDING_PAYMENT'
    ) RETURNING * INTO v_session;

    BEGIN
        INSERT INTO xera_hashrate_payments (session_id, user_id, provider, reference, amount, currency)
        VALUES (v_session.id, p_user_id, p_payment_method, p_reference, v_tier.price, v_tier.currency)
        RETURNING * INTO v_payment;
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'reference_already_used' USING ERRCODE = 'P0207';
    END;

    session_id := v_session.id;
    payment_id := v_payment.id;
    maximum_entitlement := v_entitlement;
    price := v_tier.price;
    currency := v_tier.currency;
    RETURN NEXT;
END;
$$;

-- ---- confirm: only a verified payment may activate a session --------
-- Idempotent: replaying the same reference after it's already CONFIRMED
-- is a no-op success, not an error and not a double activation (webhook
-- retries are expected and must be safe).
DROP FUNCTION IF EXISTS xera_confirm_hashrate_payment(TEXT, TEXT, JSONB);

CREATE OR REPLACE FUNCTION xera_confirm_hashrate_payment(
    p_reference             TEXT,
    p_tx_hash               TEXT DEFAULT NULL,
    p_raw_webhook           JSONB DEFAULT NULL,
    p_verified_amount_minor BIGINT DEFAULT NULL,
    p_verified_currency     TEXT DEFAULT NULL
) RETURNS xera_hashrate_sessions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_payment xera_hashrate_payments;
    v_session xera_hashrate_sessions;
BEGIN
    SELECT * INTO v_payment FROM xera_hashrate_payments WHERE reference = p_reference FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'payment_not_found' USING ERRCODE = 'P0208';
    END IF;

    IF v_payment.status = 'CONFIRMED' THEN
        -- Replay of an already-confirmed webhook: return current state, do nothing further.
        SELECT * INTO v_session FROM xera_hashrate_sessions WHERE id = v_payment.session_id;
        RETURN v_session;
    END IF;

    -- EXPIRED is allowed through: a customer can legitimately finish
    -- Paystack checkout after the stale-payment sweep has released their
    -- reservation. Rejecting that would take their money and give them
    -- nothing, so we try to re-reserve below instead.
    IF v_payment.status NOT IN ('PENDING', 'EXPIRED') THEN
        RAISE EXCEPTION 'payment_already_finalized' USING ERRCODE = 'P0209';
    END IF;

    -- The provider must prove the exact amount and currency that was paid.
    -- Paystack sends amounts in the smallest currency unit; the expected
    -- value is derived from the immutable payment row created at purchase.
    IF v_payment.provider = 'PAYSTACK' THEN
        IF p_verified_amount_minor IS NULL OR p_verified_currency IS NULL THEN
            RAISE EXCEPTION 'payment_verification_failed' USING ERRCODE = 'P0213';
        END IF;
        IF p_verified_amount_minor <> ROUND(v_payment.amount * 100)::BIGINT
           OR UPPER(p_verified_currency) <> UPPER(v_payment.currency) THEN
            RAISE EXCEPTION 'payment_verification_failed' USING ERRCODE = 'P0213';
        END IF;
    END IF;

    IF v_payment.status = 'EXPIRED' THEN
        SELECT * INTO v_session FROM xera_hashrate_sessions WHERE id = v_payment.session_id FOR UPDATE;
        IF NOT FOUND OR v_session.status <> 'EXPIRED' THEN
            RAISE EXCEPTION 'payment_already_finalized' USING ERRCODE = 'P0209';
        END IF;
        -- Re-take the reservation the sweep released. Raises
        -- entitlement_cap_exceeded (whole function rolls back, payment stays
        -- EXPIRED) if the pool can no longer back the session — the caller
        -- then flags the payment for a manual refund.
        PERFORM xera_reserve_mining_entitlement(v_session.reserved_entitlement, 'HASHRATE_LATE_PAYMENT');
    END IF;

    IF p_tx_hash IS NOT NULL THEN
        BEGIN
            UPDATE xera_hashrate_payments
                SET status = 'CONFIRMED', tx_hash = p_tx_hash, confirmed_at = now(), raw_webhook = p_raw_webhook
                WHERE reference = p_reference;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'tx_hash_already_used' USING ERRCODE = 'P0210';
        END;
    ELSE
        UPDATE xera_hashrate_payments
            SET status = 'CONFIRMED', confirmed_at = now(), raw_webhook = p_raw_webhook
            WHERE reference = p_reference;
    END IF;

    UPDATE xera_hashrate_sessions
        SET status = 'ACTIVE', started_at = now(),
            expires_at = now() + make_interval(days => duration_days),
            updated_at = now()
        WHERE id = v_payment.session_id
        RETURNING * INTO v_session;

    RETURN v_session;
END;
$$;

-- ---- release: failed/expired/cancelled payment frees the reservation -
-- Idempotent on repeat calls once already released.
CREATE OR REPLACE FUNCTION xera_release_hashrate_reservation(
    p_reference TEXT,
    p_status    TEXT -- 'FAILED' | 'EXPIRED' | 'CANCELLED'
) RETURNS xera_hashrate_sessions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_payment xera_hashrate_payments;
    v_session xera_hashrate_sessions;
BEGIN
    IF p_status NOT IN ('FAILED', 'EXPIRED', 'CANCELLED') THEN
        RAISE EXCEPTION 'invalid_release_status' USING ERRCODE = 'P0211';
    END IF;

    SELECT * INTO v_payment FROM xera_hashrate_payments WHERE reference = p_reference FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'payment_not_found' USING ERRCODE = 'P0208';
    END IF;

    IF v_payment.status IN ('FAILED', 'EXPIRED', 'CANCELLED') THEN
        -- Already released — idempotent no-op.
        SELECT * INTO v_session FROM xera_hashrate_sessions WHERE id = v_payment.session_id;
        RETURN v_session;
    END IF;

    IF v_payment.status = 'CONFIRMED' THEN
        RAISE EXCEPTION 'cannot_release_confirmed_payment' USING ERRCODE = 'P0212';
    END IF;

    UPDATE xera_hashrate_payments SET status = p_status WHERE reference = p_reference;

    UPDATE xera_hashrate_sessions
        SET status = p_status, updated_at = now()
        WHERE id = v_payment.session_id
        RETURNING * INTO v_session;

    PERFORM xera_release_mining_entitlement(v_session.reserved_entitlement);

    RETURN v_session;
END;
$$;


-- ---- hashrate reward claim -----------------------------------------
-- A paid hashrate reserves its FULL entitlement at purchase time. This
-- function does not reserve again: the reservation is already sitting in
-- xera_mining_entitlement_state and represents the maximum amount this
-- session is allowed to distribute. Claims merely move the accrued amount
-- into the user's existing XERA wallet/ledger.
--
-- Rewards accrue in complete 24-hour periods from started_at. A claim at
-- expiry can collect the final period(s), up to the immutable
-- maximum_entitlement snapshot. The transaction type remains MINING_REWARD
-- intentionally so the existing BNB/TON settlement code can recognize a
-- hashrate reward without any changes to xera/chain/claims.py.
CREATE OR REPLACE FUNCTION xera_claim_hashrate_reward(
    p_session_id BIGINT,
    p_user_id    BIGINT
) RETURNS TABLE(
    new_balance NUMERIC,
    reward_credited NUMERIC,
    rewarded_total NUMERIC,
    remaining_entitlement NUMERIC,
    status TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_session xera_hashrate_sessions;
    v_payment xera_hashrate_payments;
    v_wallet xera_wallets;
    v_alloc  xera_allocations;
    v_elapsed_days INTEGER;
    v_target NUMERIC(20,4);
    v_reward NUMERIC(20,4);
    v_reference TEXT;
    v_new_balance NUMERIC(20,4);
    v_new_status TEXT;
BEGIN
    SELECT * INTO v_session
    FROM xera_hashrate_sessions
    WHERE id = p_session_id AND user_id = p_user_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'session_not_found' USING ERRCODE = 'P0214';
    END IF;

    SELECT * INTO v_payment
    FROM xera_hashrate_payments
    WHERE session_id = v_session.id
    ORDER BY id DESC
    LIMIT 1
    FOR UPDATE;

    IF NOT FOUND OR v_payment.status <> 'CONFIRMED' THEN
        RAISE EXCEPTION 'payment_not_confirmed' USING ERRCODE = 'P0215';
    END IF;

    IF v_session.status NOT IN ('ACTIVE', 'COMPLETED') THEN
        RAISE EXCEPTION 'invalid_session_status' USING ERRCODE = 'P0216';
    END IF;

    IF v_session.started_at IS NULL THEN
        RAISE EXCEPTION 'payment_not_confirmed' USING ERRCODE = 'P0215';
    END IF;

    -- Full 24-hour periods only. Once the session expires, the full
    -- duration is available, including the final day.
    IF now() >= v_session.expires_at THEN
        v_elapsed_days := v_session.duration_days;
    ELSE
        v_elapsed_days := FLOOR(EXTRACT(EPOCH FROM (now() - v_session.started_at)) / 86400)::INTEGER;
    END IF;

    IF v_elapsed_days < 1 THEN
        RAISE EXCEPTION 'not_yet_claimable' USING ERRCODE = 'P0217';
    END IF;

    v_target := LEAST(
        v_session.maximum_entitlement,
        v_elapsed_days * v_session.daily_rate
    );
    v_reward := v_target - v_session.rewarded_amount;

    IF v_reward <= 0 THEN
        IF now() >= v_session.expires_at AND v_session.rewarded_amount >= v_session.maximum_entitlement THEN
            UPDATE xera_hashrate_sessions
            SET status = 'COMPLETED', updated_at = now()
            WHERE id = v_session.id;
        END IF;
        RAISE EXCEPTION 'nothing_to_claim' USING ERRCODE = 'P0218';
    END IF;

    -- Lock order (allocations, then wallet) matches xera_claim_mining_reward
    -- so a user claiming free-mining and hashrate rewards at the same time
    -- can't deadlock. The canonical ledger needs no update here: the full
    -- entitlement was already reserved at purchase.
    SELECT * INTO v_alloc FROM xera_allocations WHERE id = 1 FOR UPDATE;

    SELECT * INTO v_wallet
    FROM xera_wallets
    WHERE user_id = p_user_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet_not_found' USING ERRCODE = 'P0007';
    END IF;
    IF v_wallet.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'wallet_not_active' USING ERRCODE = 'P0001';
    END IF;

    -- A deterministic reference makes a retry safe: the session row is
    -- locked, so rewarded_amount can only advance once for this target.
    v_reference := 'hashrate:' || v_session.id::TEXT || ':' || to_char(v_target, 'FM999999999999990D0000');

    BEGIN
        INSERT INTO xera_transactions (
            wallet_id, user_id, type, amount, direction, reference_id, metadata
        ) VALUES (
            v_wallet.id, p_user_id, 'MINING_REWARD', v_reward, 'CREDIT', v_reference,
            jsonb_build_object(
                'source', 'HASHRATE',
                'hashrate_session_id', v_session.id,
                'tier_id', v_session.tier_id,
                'daily_rate', v_session.daily_rate,
                'accrued_days', v_elapsed_days,
                'entitlement_max', v_session.maximum_entitlement
            )
        );
    EXCEPTION WHEN unique_violation THEN
        -- Should only be reachable on an unexpected replay after the row
        -- lock has been bypassed externally. Treat it as no-op rather than
        -- crediting twice.
        RAISE EXCEPTION 'nothing_to_claim' USING ERRCODE = 'P0218';
    END;

    UPDATE xera_wallets
    SET cached_balance = cached_balance + v_reward,
        updated_at = now()
    WHERE id = v_wallet.id
    RETURNING cached_balance INTO v_new_balance;

    -- Keep the legacy distributed counter (public stats, free-mining rate)
    -- in step with what has actually been paid out. Clamped so the
    -- xera_mining_distributed_within_allocation CHECK can never turn a
    -- paid-for claim into an error.
    UPDATE xera_allocations
    SET mining_distributed = mining_distributed
            + GREATEST(0, LEAST(v_reward, v_alloc.mining_allocation - v_alloc.mining_distributed)),
        updated_at = now()
    WHERE id = 1;

    v_new_status := CASE
        WHEN v_target >= v_session.maximum_entitlement THEN 'COMPLETED'
        ELSE 'ACTIVE'
    END;

    UPDATE xera_hashrate_sessions
    SET rewarded_amount = v_target,
        status = v_new_status,
        updated_at = now()
    WHERE id = v_session.id;

    new_balance := v_new_balance;
    reward_credited := v_reward;
    rewarded_total := v_target;
    remaining_entitlement := GREATEST(v_session.maximum_entitlement - v_target, 0);
    status := v_new_status;
    RETURN NEXT;
END;
$$;

-- ---- stale pending payment cleanup --------------------------------
-- Paystack may not emit a useful failure webhook when a customer simply
-- abandons checkout. This RPC releases those reservations after a bounded
-- age. It is safe to call repeatedly from the user session endpoints or an
-- admin scheduler; already-finalized payments are ignored.
CREATE OR REPLACE FUNCTION xera_expire_stale_hashrate_payments(
    p_age_minutes INTEGER DEFAULT 30
) RETURNS TABLE(expired_count BIGINT, released_amount NUMERIC)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_payment RECORD;
    v_total NUMERIC(20,4) := 0;
    v_count BIGINT := 0;
BEGIN
    IF p_age_minutes < 5 THEN
        p_age_minutes := 5;
    END IF;

    FOR v_payment IN
        SELECT p.id, p.session_id, s.reserved_entitlement
        FROM xera_hashrate_payments p
        JOIN xera_hashrate_sessions s ON s.id = p.session_id
        WHERE p.status = 'PENDING'
          AND p.created_at <= now() - make_interval(mins => p_age_minutes)
        ORDER BY p.id
        FOR UPDATE OF p, s
    LOOP
        UPDATE xera_hashrate_payments
        SET status = 'EXPIRED'
        WHERE id = v_payment.id AND status = 'PENDING';

        IF FOUND THEN
            UPDATE xera_hashrate_sessions
            SET status = 'EXPIRED', updated_at = now()
            WHERE id = v_payment.session_id
              AND status = 'PENDING_PAYMENT';

            v_total := v_total + v_payment.reserved_entitlement;
            v_count := v_count + 1;
        END IF;
    END LOOP;

    IF v_total > 0 THEN
        PERFORM xera_release_mining_entitlement(v_total);
    END IF;

    expired_count := v_count;
    released_amount := v_total;
    RETURN NEXT;
END;
$$;

-- ------------------------------------------------------------
-- 4. RLS / PRIVILEGES — same posture as the rest of the XERA schema:
--    no Supabase-Auth-based policies (see hardening migration's section 4
--    note); service_role only, enforced in the FastAPI layer.
-- ------------------------------------------------------------

ALTER TABLE xera_mining_entitlement_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_hashrate_tiers           ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_hashrate_sessions        ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_hashrate_payments        ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON xera_mining_entitlement_state FROM PUBLIC;
REVOKE ALL ON xera_hashrate_tiers           FROM PUBLIC;
REVOKE ALL ON xera_hashrate_sessions        FROM PUBLIC;
REVOKE ALL ON xera_hashrate_payments        FROM PUBLIC;

GRANT SELECT, INSERT, UPDATE ON
    xera_mining_entitlement_state, xera_hashrate_tiers, xera_hashrate_sessions, xera_hashrate_payments
    TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;

-- ------------------------------------------------------------
-- 5. RPC EXECUTE PRIVILEGES
-- ------------------------------------------------------------
-- Postgres grants EXECUTE on new functions to PUBLIC by default, and every
-- function above is SECURITY DEFINER — so without this, anyone holding the
-- public Supabase anon key could call them straight through PostgREST's
-- /rest/v1/rpc/<name> and bypass the FastAPI layer entirely: reserve the
-- whole mining allocation, or purchase + "confirm" a hashrate session
-- without paying. The blockchain hardening migration does the same for its
-- functions (see its RPC-endpoint note); this covers every xera_* function
-- in one pass, including the free-mining ones redefined above.
DO $$
DECLARE
    f RECORD;
BEGIN
    FOR f IN
        SELECT p.oid::regprocedure AS sig
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname LIKE 'xera\_%'
    LOOP
        EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC, anon, authenticated', f.sig);
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', f.sig);
    END LOOP;
END;
$$;
