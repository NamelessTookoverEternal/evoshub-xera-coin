-- ============================================================
-- XERA — MAINNET READINESS: SEPARATE TESTNET CLAIMS FROM MAINNET
-- ============================================================
-- Why: every on-chain claim made so far was made against the BNB testnet token.
-- Without a network stamp, those rows would be counted toward the 75,000,000
-- on-chain cap once the app points at mainnet, and a FAILED/EXPIRED testnet claim
-- could be retried as a real mainnet claim.
--
-- What this does:
--   1. Adds xera_onchain_claims.network ('testnet' | 'mainnet'). EVERY existing
--      row is stamped 'testnet' (confirmed: no XERA token exists on mainnet yet).
--   2. The 75M on-chain cap counter (xera_mining_allocation_state.global_reserved_amount)
--      now means "live MAINNET claims only". It is recomputed once here from the
--      mainnet rows (none yet => 0). Testnet claims no longer touch it and are not
--      capped.
--   3. Reserve / retry take p_network (default 'testnet', so nothing changes until the
--      backend passes 'mainnet'). A claim can only be retried on the network it was
--      created on: claim_wrong_network otherwise.
--   4. Confirm / fail / expire adjust the counter only for mainnet rows.
--
-- What this does NOT do (on purpose):
--   * It does not delete, reverse or edit any claim row, ledger row or balance.
--     Balances debited by testnet claims stay debited; xera_claimable_balance is
--     unchanged and still subtracts every claim, so a testnet claim can only ever
--     REDUCE what is claimable, never create a mainnet entitlement.
--   * It does not touch the 500,000,000 supply, the 75,000,000 mining allocation
--     (xera_allocations / xera_mining_entitlement_state) or the $1 transfer fee.
--
-- Safe to re-run (idempotent).
-- ============================================================

-- ------------------------------------------------------------
-- 1. NETWORK COLUMN
-- ------------------------------------------------------------
ALTER TABLE xera_onchain_claims
    ADD COLUMN IF NOT EXISTS network TEXT NOT NULL DEFAULT 'testnet';

ALTER TABLE xera_onchain_claims DROP CONSTRAINT IF EXISTS xera_onchain_claims_network_check;
ALTER TABLE xera_onchain_claims ADD CONSTRAINT xera_onchain_claims_network_check
    CHECK (network IN ('testnet', 'mainnet'));

CREATE INDEX IF NOT EXISTS xera_onchain_claims_network_status_idx
    ON xera_onchain_claims (network, status);

-- ------------------------------------------------------------
-- 2. THE CAP COUNTER NOW MEANS "LIVE MAINNET CLAIMS"
-- ------------------------------------------------------------
-- Definition (unchanged except for the network filter): sum of claimed_amount for
-- rows in SIGNED / SUBMITTED / CONFIRMED. Recomputing from the table is exact and
-- idempotent, so no marker row is needed.
UPDATE xera_mining_allocation_state
    SET global_reserved_amount = COALESCE((
            SELECT SUM(c.claimed_amount) FROM xera_onchain_claims c
            WHERE c.network = 'mainnet' AND c.status IN ('SIGNED', 'SUBMITTED', 'CONFIRMED')
        ), 0),
        updated_at = now()
    WHERE id = 1;

-- ------------------------------------------------------------
-- 3. RESERVE (amount-based) — now network-aware
-- ------------------------------------------------------------
DROP FUNCTION IF EXISTS xera_reserve_onchain_claim_amount(TEXT, BIGINT, TEXT, TEXT, NUMERIC, NUMERIC, NUMERIC, TEXT, TIMESTAMPTZ);

CREATE OR REPLACE FUNCTION xera_reserve_onchain_claim_amount(
    p_reference_id        TEXT,
    p_user_id             BIGINT,
    p_chain               TEXT,
    p_wallet_address      TEXT,
    p_amount              NUMERIC,
    p_transferable_amount NUMERIC,
    p_locked_amount       NUMERIC,
    p_contract_address    TEXT,
    p_deadline            TIMESTAMPTZ,
    p_network             TEXT DEFAULT 'testnet'
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
    IF p_network NOT IN ('testnet', 'mainnet') THEN
        RAISE EXCEPTION 'invalid_network' USING ERRCODE = 'P0143';
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

    -- The 75M on-chain cap guards MAINNET only; testnet claims are neither capped nor counted.
    IF p_network = 'mainnet' AND v_state.global_reserved_amount + p_amount > v_state.global_cap THEN
        RAISE EXCEPTION 'global_mining_allocation_exceeded' USING ERRCODE = 'P0111';
    END IF;

    BEGIN
        INSERT INTO xera_onchain_claims (
            reference_id, user_id, chain, wallet_address,
            claimed_amount, transferable_amount, locked_amount,
            contract_address, signature_deadline, status, balance_debited, network
        ) VALUES (
            p_reference_id, p_user_id, p_chain, p_wallet_address,
            p_amount, p_transferable_amount, p_locked_amount,
            p_contract_address, p_deadline, 'SIGNED', p_amount, p_network
        )
        RETURNING * INTO v_row;
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'reference_already_reserved' USING ERRCODE = 'P0102';
    END;

    INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
    VALUES (v_wallet.id, p_user_id, 'ONCHAIN_CLAIM', p_amount, 'DEBIT', p_reference_id,
            jsonb_build_object('chain', p_chain, 'network', p_network, 'wallet_address', p_wallet_address,
                               'transferable', p_transferable_amount, 'locked', p_locked_amount));

    UPDATE xera_wallets
        SET cached_balance = cached_balance - p_amount, updated_at = now()
        WHERE id = v_wallet.id;

    IF p_network = 'mainnet' THEN
        UPDATE xera_mining_allocation_state
            SET global_reserved_amount = global_reserved_amount + p_amount, updated_at = now()
            WHERE id = 1;
    END IF;

    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 4. EXPIRE / FAIL — release the cap only for mainnet rows
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION xera_expire_stale_onchain_claims() RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_expired_count INTEGER := 0;
    v_row RECORD;
BEGIN
    FOR v_row IN
        SELECT reference_id, claimed_amount, network FROM xera_onchain_claims
        WHERE status = 'SIGNED' AND signature_deadline < now()
        FOR UPDATE
    LOOP
        UPDATE xera_onchain_claims SET status = 'EXPIRED', updated_at = now()
            WHERE reference_id = v_row.reference_id;

        IF v_row.network = 'mainnet' THEN
            UPDATE xera_mining_allocation_state
                SET global_reserved_amount = greatest(0, global_reserved_amount - v_row.claimed_amount), updated_at = now()
                WHERE id = 1;
        END IF;

        v_expired_count := v_expired_count + 1;
    END LOOP;

    RETURN v_expired_count;
END;
$$;

CREATE OR REPLACE FUNCTION xera_mark_onchain_claim_failed(
    p_reference_id TEXT
) RETURNS xera_onchain_claims
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row xera_onchain_claims;
BEGIN
    UPDATE xera_onchain_claims
        SET status = 'FAILED', updated_at = now()
        WHERE reference_id = p_reference_id AND status IN ('SIGNED', 'SUBMITTED')
        RETURNING * INTO v_row;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'claim_not_found_or_not_failable' USING ERRCODE = 'P0104';
    END IF;

    IF v_row.network = 'mainnet' THEN
        UPDATE xera_mining_allocation_state
            SET global_reserved_amount = greatest(0, global_reserved_amount - v_row.claimed_amount), updated_at = now()
            WHERE id = 1;
    END IF;

    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 5. RETRY — same network only
-- ------------------------------------------------------------
DROP FUNCTION IF EXISTS xera_retry_onchain_claim(TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ);

CREATE OR REPLACE FUNCTION xera_retry_onchain_claim(
    p_reference_id       TEXT,
    p_chain              TEXT,
    p_wallet_address     TEXT,
    p_contract_address   TEXT,
    p_deadline           TIMESTAMPTZ,
    p_network            TEXT DEFAULT 'testnet'
) RETURNS xera_onchain_claims
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row   xera_onchain_claims;
    v_state xera_mining_allocation_state;
BEGIN
    IF p_chain NOT IN ('BNB', 'TON') THEN
        RAISE EXCEPTION 'invalid_chain' USING ERRCODE = 'P0101';
    END IF;

    SELECT * INTO v_row FROM xera_onchain_claims WHERE reference_id = p_reference_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'claim_not_found' USING ERRCODE = 'P0103';
    END IF;
    IF v_row.status NOT IN ('FAILED', 'EXPIRED') THEN
        RAISE EXCEPTION 'claim_not_retryable' USING ERRCODE = 'P0112';
    END IF;
    -- A testnet claim must never become a mainnet claim (and vice versa).
    IF v_row.network <> p_network THEN
        RAISE EXCEPTION 'claim_wrong_network' USING ERRCODE = 'P0142';
    END IF;

    SELECT * INTO v_state FROM xera_mining_allocation_state WHERE id = 1 FOR UPDATE;
    IF v_row.network = 'mainnet' AND v_state.global_reserved_amount + v_row.claimed_amount > v_state.global_cap THEN
        RAISE EXCEPTION 'global_mining_allocation_exceeded' USING ERRCODE = 'P0111';
    END IF;

    UPDATE xera_onchain_claims
        SET status = 'SIGNED', chain = p_chain, wallet_address = p_wallet_address,
            contract_address = p_contract_address, signature_deadline = p_deadline,
            transaction_hash = NULL, block_number = NULL, confirmed_at = NULL, updated_at = now()
        WHERE reference_id = p_reference_id
        RETURNING * INTO v_row;

    IF v_row.network = 'mainnet' THEN
        UPDATE xera_mining_allocation_state
            SET global_reserved_amount = global_reserved_amount + v_row.claimed_amount, updated_at = now()
            WHERE id = 1;
    END IF;

    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 6. CONFIRM — count a late-confirmed FAILED/EXPIRED claim only for mainnet
-- ------------------------------------------------------------
-- If the transaction landed before the failure/expiry was noticed, the tokens really
-- left the distributor, so a mainnet claim is counted again (no cap check: the funds
-- are already gone). Testnet rows never touch the counter.
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
        RETURN v_row; -- idempotent
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

    IF v_prev_status IN ('FAILED', 'EXPIRED') AND v_row.network = 'mainnet' THEN
        UPDATE xera_mining_allocation_state
            SET global_reserved_amount = global_reserved_amount + v_row.claimed_amount, updated_at = now()
            WHERE id = 1;
    END IF;

    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 7. PRIVILEGES — same default-deny posture as the rest of the schema
-- ------------------------------------------------------------
REVOKE EXECUTE ON FUNCTION xera_reserve_onchain_claim_amount(TEXT, BIGINT, TEXT, TEXT, NUMERIC, NUMERIC, NUMERIC, TEXT, TIMESTAMPTZ, TEXT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_retry_onchain_claim(TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_expire_stale_onchain_claims() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_mark_onchain_claim_failed(TEXT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_confirm_onchain_claim(TEXT, TEXT, BIGINT) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION xera_reserve_onchain_claim_amount(TEXT, BIGINT, TEXT, TEXT, NUMERIC, NUMERIC, NUMERIC, TEXT, TIMESTAMPTZ, TEXT) TO service_role;
GRANT  EXECUTE ON FUNCTION xera_retry_onchain_claim(TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT) TO service_role;
GRANT  EXECUTE ON FUNCTION xera_expire_stale_onchain_claims() TO service_role;
GRANT  EXECUTE ON FUNCTION xera_mark_onchain_claim_failed(TEXT) TO service_role;
GRANT  EXECUTE ON FUNCTION xera_confirm_onchain_claim(TEXT, TEXT, BIGINT) TO service_role;
