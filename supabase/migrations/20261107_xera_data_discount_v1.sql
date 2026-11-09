-- ============================================================
-- XERA discount on EVOS Data bundles  (OFF by default)
-- ============================================================
-- WHAT THIS ADDS
--   * xera_discount_config  one row of settings (switch, rate, discount %, cap %, hold time, KYC rule)
--   * xera_discount_holds   one row per discounted order: XERA is HELD when payment starts,
--                           CONSUMED when Paystack confirms, RELEASED/EXPIRED if the buyer never pays
--   * ledger type DISCOUNT_SPEND  (a normal DEBIT row in xera_transactions)
--   * functions: xera_discount_spendable, xera_discount_hold, xera_discount_consume,
--                xera_discount_release, xera_discount_refund
--
-- SAFETY
--   * Nothing changes for anyone until you run the "turn on" statement at the bottom.
--   * Balances move ONLY inside these functions (wallet row locked FOR UPDATE), same rule as the rest of XERA.
--   * Spendable XERA = wallet balance - active holds, so one balance cannot be promised to two orders.
--   * xera_claimable_balance already caps claimable at the wallet balance, so XERA spent on a discount
--     can never also be claimed on-chain.
--   * If a payment arrives after its hold expired, or the balance dropped in between, the discount is
--     still honoured: whatever XERA is left is debited and the gap is recorded in xera_discount_holds.shortfall.
--   * Spent XERA is NOT returned to the 75M mining pool and no allocation number is touched.
-- Safe to re-run. Run in the Supabase SQL Editor (production).
-- ============================================================

-- ------------------------------------------------------------
-- 1. SETTINGS
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_discount_config (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    enabled       BOOLEAN NOT NULL DEFAULT false,
    xera_per_ghs  NUMERIC(20,4) NOT NULL DEFAULT 100 CHECK (xera_per_ghs > 0),   -- 100 XERA = GHS 1.00 off
    discount_pct  NUMERIC(5,2)  NOT NULL DEFAULT 4   CHECK (discount_pct >= 0 AND discount_pct <= 100),
    max_pct       NUMERIC(5,2)  NOT NULL DEFAULT 10  CHECK (max_pct >= 0 AND max_pct <= 100),
    hold_minutes  INTEGER NOT NULL DEFAULT 30 CHECK (hold_minutes BETWEEN 5 AND 240),
    require_kyc   BOOLEAN NOT NULL DEFAULT true,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT xera_discount_pct_within_cap CHECK (discount_pct <= max_pct)
);
INSERT INTO xera_discount_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ------------------------------------------------------------
-- 2. HOLDS
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_discount_holds (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id),
    order_ref     TEXT NOT NULL UNIQUE,                    -- the Paystack reference of the order
    xera_amount   NUMERIC(20,4) NOT NULL CHECK (xera_amount > 0),
    discount_ghs  NUMERIC(12,2) NOT NULL CHECK (discount_ghs > 0),
    status        TEXT NOT NULL DEFAULT 'HELD'
                  CHECK (status IN ('HELD','CONSUMED','RELEASED','EXPIRED','REFUNDED')),
    xera_debited  NUMERIC(20,4) NOT NULL DEFAULT 0,        -- what was really taken from the wallet
    shortfall     NUMERIC(20,4) NOT NULL DEFAULT 0,        -- xera_amount - xera_debited (discount honoured anyway)
    late          BOOLEAN NOT NULL DEFAULT false,          -- payment arrived after the hold had expired
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL,
    settled_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_xera_discount_holds_user ON xera_discount_holds (user_id, status, expires_at);

ALTER TABLE xera_discount_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_discount_holds  ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON xera_discount_config, xera_discount_holds FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON xera_discount_config, xera_discount_holds TO service_role;
GRANT USAGE, SELECT ON SEQUENCE xera_discount_holds_id_seq TO service_role;

-- ------------------------------------------------------------
-- 3. LEDGER TYPE  (keeps every existing type)
-- ------------------------------------------------------------
ALTER TABLE xera_transactions DROP CONSTRAINT IF EXISTS xera_transactions_type_check;
ALTER TABLE xera_transactions ADD CONSTRAINT xera_transactions_type_check CHECK (type IN (
    'MINING_REWARD','XERA_PURCHASE','REFERRAL_REWARD','BONUS','DAILY_CLAIM',
    'ADMIN_CREDIT','ADMIN_DEBIT','REVERSAL','MIGRATION','ONCHAIN_CLAIM','DISCOUNT_SPEND'
));

-- One discount debit per order, and one refund per order (idempotency backstops).
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_discount_spend_unique
    ON xera_transactions (reference_id) WHERE type = 'DISCOUNT_SPEND';
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_discount_refund_unique
    ON xera_transactions (reference_id) WHERE type = 'REVERSAL' AND reference_id LIKE 'discount-refund:%';

-- ------------------------------------------------------------
-- 4. SPENDABLE BALANCE (read-only)
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION xera_discount_spendable(p_user_id BIGINT)
RETURNS NUMERIC
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT GREATEST(0,
        COALESCE((SELECT w.cached_balance FROM xera_wallets w WHERE w.user_id = p_user_id), 0)
      - COALESCE((SELECT SUM(h.xera_amount) FROM xera_discount_holds h
                   WHERE h.user_id = p_user_id AND h.status = 'HELD' AND h.expires_at > now()), 0));
$$;

-- ------------------------------------------------------------
-- 5. HOLD  (payment is about to start)
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION xera_discount_hold(
    p_user_id      BIGINT,
    p_order_ref    TEXT,
    p_xera         NUMERIC,
    p_discount_ghs NUMERIC,
    p_minutes      INTEGER
) RETURNS xera_discount_holds
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_wallet xera_wallets;
    v_held   NUMERIC;
    v_row    xera_discount_holds;
BEGIN
    IF p_xera IS NULL OR p_xera <= 0 OR p_discount_ghs IS NULL OR p_discount_ghs <= 0 THEN
        RAISE EXCEPTION 'invalid_amount' USING ERRCODE = 'P0109';
    END IF;

    SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet_not_found' USING ERRCODE = 'P0007';
    END IF;
    IF v_wallet.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'wallet_not_active' USING ERRCODE = 'P0001';
    END IF;

    -- Old unpaid holds stop counting.
    UPDATE xera_discount_holds
       SET status = 'EXPIRED', settled_at = now()
     WHERE user_id = p_user_id AND status = 'HELD' AND expires_at <= now();

    SELECT COALESCE(SUM(xera_amount), 0) INTO v_held
      FROM xera_discount_holds WHERE user_id = p_user_id AND status = 'HELD';

    IF v_wallet.cached_balance - v_held < p_xera THEN
        RAISE EXCEPTION 'insufficient_balance' USING ERRCODE = 'P0010';
    END IF;

    INSERT INTO xera_discount_holds (user_id, order_ref, xera_amount, discount_ghs, expires_at)
    VALUES (p_user_id, p_order_ref, p_xera, p_discount_ghs, now() + make_interval(mins => p_minutes))
    RETURNING * INTO v_row;
    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 6. CONSUME  (Paystack confirmed the payment) — idempotent
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION xera_discount_consume(p_order_ref TEXT)
RETURNS xera_discount_holds
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_hold   xera_discount_holds;
    v_wallet xera_wallets;
    v_debit  NUMERIC;
    v_late   BOOLEAN;
BEGIN
    SELECT * INTO v_hold FROM xera_discount_holds WHERE order_ref = p_order_ref FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;                         -- this order had no XERA discount
    END IF;
    IF v_hold.status IN ('CONSUMED','REFUNDED') THEN
        RETURN v_hold;                       -- already settled
    END IF;

    SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = v_hold.user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet_not_found' USING ERRCODE = 'P0007';
    END IF;

    v_late  := v_hold.status IN ('RELEASED','EXPIRED') OR v_hold.expires_at <= now();
    v_debit := LEAST(v_hold.xera_amount, v_wallet.cached_balance);

    IF v_debit > 0 THEN
        INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
        VALUES (v_wallet.id, v_hold.user_id, 'DISCOUNT_SPEND', v_debit, 'DEBIT', p_order_ref,
                jsonb_build_object('reason', 'evosdata_discount', 'discount_ghs', v_hold.discount_ghs,
                                   'xera_planned', v_hold.xera_amount, 'late', v_late));
        UPDATE xera_wallets
           SET cached_balance = cached_balance - v_debit, updated_at = now()
         WHERE id = v_wallet.id;
    END IF;

    UPDATE xera_discount_holds
       SET status = 'CONSUMED', xera_debited = v_debit, shortfall = v_hold.xera_amount - v_debit,
           late = v_late, settled_at = now()
     WHERE id = v_hold.id
     RETURNING * INTO v_hold;
    RETURN v_hold;
END;
$$;

-- ------------------------------------------------------------
-- 7. RELEASE  (buyer never paid)
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION xera_discount_release(p_order_ref TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_n INTEGER;
BEGIN
    UPDATE xera_discount_holds SET status = 'RELEASED', settled_at = now()
     WHERE order_ref = p_order_ref AND status = 'HELD';
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n > 0;
END;
$$;

-- ------------------------------------------------------------
-- 8. REFUND  (admin only, run by hand when an order is refunded)
-- ------------------------------------------------------------
--   SELECT xera_discount_refund('<paystack reference>');
CREATE OR REPLACE FUNCTION xera_discount_refund(p_order_ref TEXT)
RETURNS NUMERIC
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_hold   xera_discount_holds;
    v_wallet xera_wallets;
BEGIN
    SELECT * INTO v_hold FROM xera_discount_holds WHERE order_ref = p_order_ref FOR UPDATE;
    IF NOT FOUND OR v_hold.status <> 'CONSUMED' OR v_hold.xera_debited <= 0 THEN
        RETURN 0;                            -- nothing was taken, or already refunded
    END IF;

    SELECT * INTO v_wallet FROM xera_wallets WHERE user_id = v_hold.user_id FOR UPDATE;

    INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
    VALUES (v_wallet.id, v_hold.user_id, 'REVERSAL', v_hold.xera_debited, 'CREDIT',
            'discount-refund:' || p_order_ref,
            jsonb_build_object('reason', 'evosdata_discount_refund', 'order_ref', p_order_ref));
    UPDATE xera_wallets SET cached_balance = cached_balance + v_hold.xera_debited, updated_at = now()
     WHERE id = v_wallet.id;
    UPDATE xera_discount_holds SET status = 'REFUNDED', settled_at = now() WHERE id = v_hold.id;
    RETURN v_hold.xera_debited;
END;
$$;

REVOKE EXECUTE ON FUNCTION xera_discount_spendable(BIGINT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION xera_discount_hold(BIGINT, TEXT, NUMERIC, NUMERIC, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION xera_discount_consume(TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION xera_discount_release(TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION xera_discount_refund(TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION xera_discount_spendable(BIGINT) TO service_role;
GRANT EXECUTE ON FUNCTION xera_discount_hold(BIGINT, TEXT, NUMERIC, NUMERIC, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION xera_discount_consume(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION xera_discount_release(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION xera_discount_refund(TEXT) TO service_role;

-- ============================================================
-- TURN ON / OFF / CHANGE  (run separately, when you are ready)
-- ============================================================
--   UPDATE xera_discount_config SET enabled = true,  updated_at = now() WHERE id = 1;   -- on
--   UPDATE xera_discount_config SET enabled = false, updated_at = now() WHERE id = 1;   -- off
--   UPDATE xera_discount_config SET xera_per_ghs = 100, discount_pct = 4, max_pct = 10 WHERE id = 1;
