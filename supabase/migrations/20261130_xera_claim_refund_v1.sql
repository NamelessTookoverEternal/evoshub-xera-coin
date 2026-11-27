-- ============================================================
-- XERA — REFUND AN UNFINISHED ON-CHAIN CLAIM
-- ============================================================
-- A claim the user never finished (wallet popup closed, app left) shows "Try again". Until now the
-- XERA stayed held for it forever. This adds a way to give it back to the in-app balance:
--
--   * the user taps Cancel next to "Try again", or
--   * the server does it by itself 2 hours after the claim was signed.
--
-- SAFETY (the backend enforces the first two before calling this):
--   1. The signature deadline has passed, so the old signature can no longer be used on-chain.
--   2. The distributor contract says the reference was NOT consumed (nothing was paid out).
--   3. This function only touches EXPIRED / FAILED rows that never recorded a transaction.
-- A cancelled claim is final: it can't be retried or confirmed (the reference stays consumed).
--
-- The global mining-pool slice was already released when the row became EXPIRED / FAILED.
-- Safe to re-run.
-- ============================================================

ALTER TABLE xera_onchain_claims DROP CONSTRAINT IF EXISTS xera_onchain_claims_status_check;
ALTER TABLE xera_onchain_claims ADD CONSTRAINT xera_onchain_claims_status_check
    CHECK (status IN ('SIGNED', 'SUBMITTED', 'CONFIRMED', 'FAILED', 'EXPIRED', 'CANCELLED'));

-- Cancelled claims no longer count as "already moved on-chain", so the balance is claimable again.
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
          AND (
                t.type IN ('MINING_REWARD', 'DAILY_CLAIM', 'REFERRAL_REWARD')
                OR (t.type = 'BONUS' AND t.reference_id LIKE 'early-miner-bonus:%')
              );

    SELECT COALESCE(SUM(c.claimed_amount), 0) INTO v_onchain
        FROM xera_onchain_claims c
        WHERE c.user_id = p_user_id AND c.status <> 'CANCELLED';

    cached_balance := COALESCE(v_cached, 0);
    eligible_total := v_elig;
    onchain_total  := v_onchain;
    claimable      := GREATEST(0, LEAST(COALESCE(v_cached, 0), v_elig - v_onchain));
    RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION xera_cancel_onchain_claim(
    p_reference_id TEXT,
    p_user_id      BIGINT
) RETURNS NUMERIC
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row    xera_onchain_claims;
    v_wallet xera_wallets;
BEGIN
    SELECT * INTO v_row FROM xera_onchain_claims WHERE reference_id = p_reference_id FOR UPDATE;
    IF NOT FOUND OR v_row.user_id <> p_user_id THEN
        RAISE EXCEPTION 'claim_not_found' USING ERRCODE = 'P0103';
    END IF;
    IF v_row.status = 'CANCELLED' THEN
        RETURN 0;                                   -- already refunded: idempotent
    END IF;
    IF v_row.status NOT IN ('EXPIRED', 'FAILED') OR v_row.transaction_hash IS NOT NULL
       OR v_row.signature_deadline >= now() THEN
        RAISE EXCEPTION 'claim_not_cancellable' USING ERRCODE = 'P0113';
    END IF;

    SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet_not_found' USING ERRCODE = 'P0007';
    END IF;

    IF v_row.balance_debited > 0 THEN
        INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
        VALUES (v_wallet.id, p_user_id, 'REVERSAL', v_row.balance_debited, 'CREDIT',
                'onchain-claim-refund:' || p_reference_id,
                jsonb_build_object('reason', 'onchain_claim_cancelled', 'claim_reference', p_reference_id));
        UPDATE xera_wallets SET cached_balance = cached_balance + v_row.balance_debited, updated_at = now()
         WHERE id = v_wallet.id;
    END IF;

    UPDATE xera_onchain_claims SET status = 'CANCELLED', updated_at = now()
     WHERE reference_id = p_reference_id;

    RETURN v_row.balance_debited;
END;
$$;

REVOKE EXECUTE ON FUNCTION xera_cancel_onchain_claim(TEXT, BIGINT) FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION xera_cancel_onchain_claim(TEXT, BIGINT) TO service_role;
