-- ============================================================
-- XERA: USDT (BEP-20) payments via NOWPayments — hashrate purchases
-- ============================================================
-- Additive + one function replacement. Safe to run on production, re-runnable.
--
-- HOW TO RUN (manual): Supabase dashboard -> SQL Editor -> paste -> Run.
--
-- WHY
--   Hashrate tiers are priced in GHS, but crypto is charged in USD. At purchase
--   time the backend converts once and stores the exact USD amount it asked
--   NOWPayments for (charge_amount_minor / charge_currency). When the payment is
--   confirmed, this function compares the price NOWPayments says it settled
--   against that STORED figure — never against a live exchange rate — and refuses
--   to activate the session on any mismatch. Before this migration the amount
--   check only existed for PAYSTACK.
-- ============================================================

ALTER TABLE xera_hashrate_payments
    ADD COLUMN IF NOT EXISTS charge_amount_minor BIGINT,
    ADD COLUMN IF NOT EXISTS charge_currency     TEXT;

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
        SELECT * INTO v_session FROM xera_hashrate_sessions WHERE id = v_payment.session_id;
        RETURN v_session;
    END IF;

    IF v_payment.status NOT IN ('PENDING', 'EXPIRED') THEN
        RAISE EXCEPTION 'payment_already_finalized' USING ERRCODE = 'P0209';
    END IF;

    -- The provider must prove the exact amount and currency that was paid.
    IF v_payment.provider = 'PAYSTACK' THEN
        IF p_verified_amount_minor IS NULL OR p_verified_currency IS NULL THEN
            RAISE EXCEPTION 'payment_verification_failed' USING ERRCODE = 'P0213';
        END IF;
        IF p_verified_amount_minor <> ROUND(v_payment.amount * 100)::BIGINT
           OR UPPER(p_verified_currency) <> UPPER(v_payment.currency) THEN
            RAISE EXCEPTION 'payment_verification_failed' USING ERRCODE = 'P0213';
        END IF;
    ELSIF v_payment.provider = 'CRYPTO' THEN
        -- Compared against the USD amount stored at purchase time. A crypto payment row
        -- with no stored charge can never be confirmed.
        IF v_payment.charge_amount_minor IS NULL OR v_payment.charge_currency IS NULL
           OR p_verified_amount_minor IS NULL OR p_verified_currency IS NULL THEN
            RAISE EXCEPTION 'payment_verification_failed' USING ERRCODE = 'P0213';
        END IF;
        IF p_verified_amount_minor <> v_payment.charge_amount_minor
           OR UPPER(p_verified_currency) <> UPPER(v_payment.charge_currency) THEN
            RAISE EXCEPTION 'payment_verification_failed' USING ERRCODE = 'P0213';
        END IF;
        -- A crypto confirmation must carry the provider's payment id as its tx_hash
        -- (replay protection via the unique index on confirmed tx_hash).
        IF p_tx_hash IS NULL THEN
            RAISE EXCEPTION 'payment_verification_failed' USING ERRCODE = 'P0213';
        END IF;
    END IF;

    IF v_payment.status = 'EXPIRED' THEN
        SELECT * INTO v_session FROM xera_hashrate_sessions WHERE id = v_payment.session_id FOR UPDATE;
        IF NOT FOUND OR v_session.status <> 'EXPIRED' THEN
            RAISE EXCEPTION 'payment_already_finalized' USING ERRCODE = 'P0209';
        END IF;
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

-- CREATE OR REPLACE keeps existing grants, but state them so a fresh run is identical.
REVOKE EXECUTE ON FUNCTION xera_confirm_hashrate_payment(TEXT, TEXT, JSONB, BIGINT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION xera_confirm_hashrate_payment(TEXT, TEXT, JSONB, BIGINT, TEXT) TO service_role;

-- Verify:
--   SELECT column_name FROM information_schema.columns
--    WHERE table_name = 'xera_hashrate_payments' AND column_name LIKE 'charge_%';   -- 2 rows
