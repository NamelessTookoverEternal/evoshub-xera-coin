-- ============================================================
-- XERA blockchain hardening — SQL-level test suite.
--
-- These are not mocked: run this against a REAL, disposable Postgres
-- database (see run_tests.sh in this directory) with both migrations
-- already applied. Uses plain assertions (RAISE EXCEPTION on failure)
-- rather than pgTAP, so it has zero extra extension dependencies.
--
-- Covers Phase 3's explicit required cases: normal reservation, exactly
-- at 75M, exceeding 75M, concurrent BNB+TON reservations (see
-- run_concurrency_test.sh — a single SQL script can't fork two real
-- concurrent sessions), duplicate reference ID, failed transaction state,
-- and the retry-without-replay path.
-- ============================================================

\set ON_ERROR_STOP on

DO $$
DECLARE
    v_status TEXT;
    v_reserved NUMERIC;
BEGIN
    -- ---- Setup: clean slate ----
    DELETE FROM xera_onchain_claims;
    UPDATE xera_mining_allocation_state SET global_reserved_amount = 0;
    DELETE FROM users WHERE id IN (901, 902, 903);
    INSERT INTO users (id, username) VALUES (901, 'test-alice'), (902, 'test-bob'), (903, 'test-carol');

    -- ---- 1. Normal reservation succeeds ----
    SELECT status INTO v_status FROM xera_reserve_onchain_claim(
        'test-ref-1', 901, 'BNB', '0xaaa', 1000, 250, 750, '0xdist', now() + interval '1 hour');
    IF v_status != 'SIGNED' THEN
        RAISE EXCEPTION 'TEST FAILED: normal reservation did not return SIGNED (got %)', v_status;
    END IF;
    RAISE NOTICE 'PASS: normal reservation';

    -- ---- 2. Reservation at exactly 75,000,000 total succeeds ----
    UPDATE xera_mining_allocation_state SET global_reserved_amount = 74999000;
    SELECT status INTO v_status FROM xera_reserve_onchain_claim(
        'test-ref-2', 902, 'TON', 'EQaaa', 1000, 250, 750, 'EQdist', now() + interval '1 hour');
    IF v_status != 'SIGNED' THEN
        RAISE EXCEPTION 'TEST FAILED: exact-cap reservation did not succeed (got %)', v_status;
    END IF;
    SELECT global_reserved_amount INTO v_reserved FROM xera_mining_allocation_state WHERE id = 1;
    IF v_reserved != 75000000 THEN
        RAISE EXCEPTION 'TEST FAILED: expected global_reserved_amount = 75000000, got %', v_reserved;
    END IF;
    RAISE NOTICE 'PASS: reservation at exactly the 75M cap';

    -- ---- 3. Reservation exceeding 75,000,000 fails closed ----
    BEGIN
        PERFORM xera_reserve_onchain_claim(
            'test-ref-3', 903, 'BNB', '0xbbb', 1, 0.25, 0.75, '0xdist', now() + interval '1 hour');
        RAISE EXCEPTION 'TEST FAILED: over-cap reservation should have raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE != 'P0111' THEN
            RAISE EXCEPTION 'TEST FAILED: expected P0111 global_mining_allocation_exceeded, got % (%)', SQLSTATE, SQLERRM;
        END IF;
    END;
    RAISE NOTICE 'PASS: over-cap reservation rejected';

    -- ---- 4. Duplicate reference_id rejected, even on a different chain ----
    -- (reset headroom first so THIS check, not the cap, is what's being tested)
    UPDATE xera_mining_allocation_state SET global_reserved_amount = 1000;
    BEGIN
        PERFORM xera_reserve_onchain_claim(
            'test-ref-1', 901, 'TON', 'EQccc', 1000, 250, 750, 'EQdist', now() + interval '1 hour');
        RAISE EXCEPTION 'TEST FAILED: duplicate reference_id on another chain should have raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE != 'P0102' THEN
            RAISE EXCEPTION 'TEST FAILED: expected P0102 reference_already_reserved, got % (%)', SQLSTATE, SQLERRM;
        END IF;
    END;
    RAISE NOTICE 'PASS: cross-chain duplicate reference_id rejected';

    -- restore the at-cap state the remaining steps assume
    UPDATE xera_mining_allocation_state SET global_reserved_amount = 75000000;

    -- ---- 5. Failed transaction state frees global capacity ----
    PERFORM xera_mark_onchain_claim_failed('test-ref-1');
    SELECT global_reserved_amount INTO v_reserved FROM xera_mining_allocation_state WHERE id = 1;
    IF v_reserved != 74999000 THEN
        RAISE EXCEPTION 'TEST FAILED: expected global_reserved_amount = 74999000 after failure, got %', v_reserved;
    END IF;
    RAISE NOTICE 'PASS: marking a claim failed frees its reserved capacity';

    -- ---- 6. A FAILED reference_id still can't be freshly re-reserved (must use retry) ----
    BEGIN
        PERFORM xera_reserve_onchain_claim(
            'test-ref-1', 901, 'TON', 'EQccc', 1000, 250, 750, 'EQdist', now() + interval '1 hour');
        RAISE EXCEPTION 'TEST FAILED: re-reserving a FAILED reference_id via fresh INSERT should have raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE != 'P0102' THEN
            RAISE EXCEPTION 'TEST FAILED: expected P0102 on FAILED-reference re-reservation attempt, got % (%)', SQLSTATE, SQLERRM;
        END IF;
    END;
    RAISE NOTICE 'PASS: FAILED reference_id cannot be re-reserved via fresh INSERT (must retry the same row)';

    -- ---- 7. Retry reuses the SAME row, re-reserves capacity, allows chain change ----
    SELECT status INTO v_status FROM xera_retry_onchain_claim(
        'test-ref-1', 'TON', 'EQccc', 'EQdist', now() + interval '1 hour');
    IF v_status != 'SIGNED' THEN
        RAISE EXCEPTION 'TEST FAILED: retry did not return SIGNED (got %)', v_status;
    END IF;
    IF (SELECT count(*) FROM xera_onchain_claims WHERE reference_id = 'test-ref-1') != 1 THEN
        RAISE EXCEPTION 'TEST FAILED: retry must reuse the same row, not create a second one';
    END IF;
    RAISE NOTICE 'PASS: retry reuses the same reservation row (no second claim created)';

    -- ---- 8. Retry is rejected once the claim is CONFIRMED ----
    PERFORM xera_confirm_onchain_claim('test-ref-1', '0xdeadbeef', 12345);
    BEGIN
        PERFORM xera_retry_onchain_claim('test-ref-1', 'BNB', '0xnew', '0xdist', now() + interval '1 hour');
        RAISE EXCEPTION 'TEST FAILED: retrying a CONFIRMED claim should have raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE != 'P0112' THEN
            RAISE EXCEPTION 'TEST FAILED: expected P0112 claim_not_retryable, got % (%)', SQLSTATE, SQLERRM;
        END IF;
    END;
    RAISE NOTICE 'PASS: a CONFIRMED claim cannot be retried';

    -- ---- 9. Confirmation is idempotent ----
    SELECT status INTO v_status FROM xera_confirm_onchain_claim('test-ref-1', '0xdeadbeef', 12345);
    IF v_status != 'CONFIRMED' THEN
        RAISE EXCEPTION 'TEST FAILED: idempotent re-confirmation did not return CONFIRMED';
    END IF;
    RAISE NOTICE 'PASS: confirming an already-CONFIRMED claim is idempotent';

    RAISE NOTICE '=== ALL SQL-LEVEL TESTS PASSED ===';
END $$;

-- ============================================================
-- Wallet-link nonce consumption (Phase 8)
-- ============================================================
DO $$
DECLARE
    v_nonce TEXT;
BEGIN
    DELETE FROM xera_wallet_link_nonces WHERE nonce LIKE 'test-nonce-%';
    DELETE FROM users WHERE id = 950;
    INSERT INTO users (id, username) VALUES (950, 'nonce-test');

    INSERT INTO xera_wallet_link_nonces (user_id, chain, address, nonce, expires_at)
    VALUES (950, 'BNB', '0xAbC123', 'test-nonce-1', now() + interval '5 minutes');

    -- 1. Normal consumption succeeds
    SELECT nonce INTO v_nonce FROM xera_consume_wallet_nonce(950, 'BNB', '0xabc123', 'test-nonce-1');
    IF v_nonce != 'test-nonce-1' THEN
        RAISE EXCEPTION 'TEST FAILED: normal nonce consumption did not succeed';
    END IF;
    RAISE NOTICE 'PASS: nonce consumption (case-insensitive address match)';

    -- 2. Reuse rejected (single-use)
    BEGIN
        PERFORM xera_consume_wallet_nonce(950, 'BNB', '0xabc123', 'test-nonce-1');
        RAISE EXCEPTION 'TEST FAILED: nonce reuse should have raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE != 'P0121' THEN
            RAISE EXCEPTION 'TEST FAILED: expected P0121 nonce_already_consumed, got % (%)', SQLSTATE, SQLERRM;
        END IF;
    END;
    RAISE NOTICE 'PASS: nonce is single-use';

    -- 3. Wrong user rejected, and deliberately vague (must NOT confirm another user's nonce exists)
    INSERT INTO xera_wallet_link_nonces (user_id, chain, address, nonce, expires_at)
    VALUES (950, 'BNB', '0xAbC123', 'test-nonce-2', now() + interval '5 minutes');
    BEGIN
        PERFORM xera_consume_wallet_nonce(999, 'BNB', '0xabc123', 'test-nonce-2');
        RAISE EXCEPTION 'TEST FAILED: wrong-user nonce consumption should have raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE != 'P0120' THEN
            RAISE EXCEPTION 'TEST FAILED: expected P0120 nonce_not_found for wrong user, got % (%)', SQLSTATE, SQLERRM;
        END IF;
    END;
    RAISE NOTICE 'PASS: nonce is bound to the issuing user';

    -- 4. Wrong address rejected
    BEGIN
        PERFORM xera_consume_wallet_nonce(950, 'BNB', '0xSOMEOTHERADDRESS', 'test-nonce-2');
        RAISE EXCEPTION 'TEST FAILED: wrong-address nonce consumption should have raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE != 'P0123' THEN
            RAISE EXCEPTION 'TEST FAILED: expected P0123 nonce_address_mismatch, got % (%)', SQLSTATE, SQLERRM;
        END IF;
    END;
    RAISE NOTICE 'PASS: nonce is bound to the requested wallet address';

    -- 5. A FAILED attempt must not burn the nonce
    IF (SELECT consumed_at FROM xera_wallet_link_nonces WHERE nonce = 'test-nonce-2') IS NOT NULL THEN
        RAISE EXCEPTION 'TEST FAILED: a rejected attempt must not consume the nonce';
    END IF;
    RAISE NOTICE 'PASS: rejected attempts do not consume the nonce';

    -- 6. Wrong chain rejected
    BEGIN
        PERFORM xera_consume_wallet_nonce(950, 'TON', '0xabc123', 'test-nonce-2');
        RAISE EXCEPTION 'TEST FAILED: wrong-chain nonce consumption should have raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE != 'P0120' THEN
            RAISE EXCEPTION 'TEST FAILED: expected P0120 for wrong chain, got % (%)', SQLSTATE, SQLERRM;
        END IF;
    END;
    RAISE NOTICE 'PASS: nonce is bound to the issuing chain';

    -- 7. Expired nonce rejected
    INSERT INTO xera_wallet_link_nonces (user_id, chain, address, nonce, expires_at)
    VALUES (950, 'BNB', '0xAbC123', 'test-nonce-3', now() - interval '1 minute');
    BEGIN
        PERFORM xera_consume_wallet_nonce(950, 'BNB', '0xabc123', 'test-nonce-3');
        RAISE EXCEPTION 'TEST FAILED: expired nonce should have raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE != 'P0122' THEN
            RAISE EXCEPTION 'TEST FAILED: expected P0122 nonce_expired, got % (%)', SQLSTATE, SQLERRM;
        END IF;
    END;
    RAISE NOTICE 'PASS: expired nonce rejected';

    RAISE NOTICE '=== ALL NONCE TESTS PASSED ===';
END $$;
