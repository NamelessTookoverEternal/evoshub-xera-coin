-- ============================================================
-- XERA: paid name change (fix a wrong / fake name)
-- ============================================================
-- WHAT THIS DOES
--   1. xera_name_change_config   enabled / fee (default 100 Pure XERA) / free slots per person (default 1).
--   2. xera_name_changes         append-only history: old name, new name, fee, when, who.
--   3. xera_name_change_allowance  extra slots an admin grants one person (support cases).
--   4. Ledger type NAME_CHANGE_FEE (all existing types kept).
--   5. xera_change_name()        the ONLY path that changes a name. In one transaction it
--        checks the rules, debits the fee, writes the ledger row, saves the history row
--        and updates users.full_name. Idempotent on request_id.
--   6. xera_name_change_fee_summary()  look-only total for the admin Vaults tab.
--
-- RULES (enforced here, not only in the app)
--   * Locked once KYC is VERIFIED or PENDING (the name must match the ID being checked).
--   * One paid change per person, plus any slots an admin granted.
--   * Fee comes from SPENDABLE Pure XERA (tokens held for a pending data order can't be used).
--   * The fee is not paid to any wallet. Like the P2P fee it is debited and recorded in the
--     ledger as NAME_CHANGE_FEE and shown as a look-only total.
--
-- WHAT THIS DOES NOT TOUCH
--   On-chain claims, withdrawals, mining, referrals, KYC, P2P, allocations.
--
-- Additive, re-runnable. Run in Supabase SQL Editor (production).
-- Error codes: P0501 name_change_disabled, P0502 kyc_locked, P0503 no_change_left,
--   P0504 same_name, P0505 user_not_found; plus existing P0001 wallet_not_active,
--   P0007 wallet_not_found, P0009 invalid_request, P0010 insufficient_balance.
-- ============================================================

BEGIN;

-- 1. settings
CREATE TABLE IF NOT EXISTS xera_name_change_config (
    id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled     BOOLEAN       NOT NULL DEFAULT true,
    fee         NUMERIC(20,4) NOT NULL DEFAULT 100 CHECK (fee >= 0),
    max_changes INTEGER       NOT NULL DEFAULT 1   CHECK (max_changes >= 0),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);
INSERT INTO xera_name_change_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- 2. history
CREATE TABLE IF NOT EXISTS xera_name_changes (
    id          BIGSERIAL PRIMARY KEY,
    request_id  TEXT          NOT NULL UNIQUE,
    user_id     BIGINT        NOT NULL,
    old_name    TEXT,
    new_name    TEXT          NOT NULL,
    fee_amount  NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK (fee_amount >= 0),
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS xera_name_changes_user_idx ON xera_name_changes (user_id, created_at DESC);

-- 3. extra slots granted by an admin
CREATE TABLE IF NOT EXISTS xera_name_change_allowance (
    user_id     BIGINT PRIMARY KEY,
    extra_slots INTEGER     NOT NULL DEFAULT 0 CHECK (extra_slots >= 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. ledger type (keeps every existing type)
ALTER TABLE xera_transactions DROP CONSTRAINT IF EXISTS xera_transactions_type_check;
ALTER TABLE xera_transactions ADD CONSTRAINT xera_transactions_type_check CHECK (type IN (
    'MINING_REWARD','XERA_PURCHASE','REFERRAL_REWARD','BONUS','DAILY_CLAIM',
    'ADMIN_CREDIT','ADMIN_DEBIT','REVERSAL','MIGRATION','ONCHAIN_CLAIM','DISCOUNT_SPEND',
    'P2P_SEND','P2P_RECEIVE','P2P_FEE','NAME_CHANGE_FEE'
));
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_name_change_fee_unique
    ON xera_transactions (reference_id) WHERE type = 'NAME_CHANGE_FEE';

-- 5. THE NAME CHANGE
CREATE OR REPLACE FUNCTION xera_change_name(
    p_user_id    BIGINT,
    p_new_name   TEXT,
    p_request_id TEXT
) RETURNS xera_name_changes
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_cfg      xera_name_change_config;
    v_existing xera_name_changes;
    v_old      TEXT;
    v_new      TEXT;
    v_w        xera_wallets;
    v_used     INTEGER;
    v_extra    INTEGER;
    v_row      xera_name_changes;
BEGIN
    v_new := btrim(regexp_replace(COALESCE(p_new_name, ''), '\s+', ' ', 'g'));
    IF v_new = '' OR p_request_id IS NULL OR btrim(p_request_id) = '' THEN
        RAISE EXCEPTION 'invalid_request' USING ERRCODE = 'P0009';
    END IF;

    -- Retry / double tap: same request id returns the original result, charges nothing.
    SELECT * INTO v_existing FROM xera_name_changes WHERE request_id = p_request_id;
    IF FOUND THEN
        IF v_existing.user_id <> p_user_id THEN
            RAISE EXCEPTION 'invalid_request' USING ERRCODE = 'P0009';
        END IF;
        RETURN v_existing;
    END IF;

    SELECT * INTO v_cfg FROM xera_name_change_config WHERE id = 1;
    IF NOT COALESCE(v_cfg.enabled, false) THEN
        RAISE EXCEPTION 'name_change_disabled' USING ERRCODE = 'P0501';
    END IF;

    SELECT full_name INTO v_old FROM users WHERE id = p_user_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'user_not_found' USING ERRCODE = 'P0505';
    END IF;
    IF lower(btrim(COALESCE(v_old, ''))) = lower(v_new) THEN
        RAISE EXCEPTION 'same_name' USING ERRCODE = 'P0504';
    END IF;

    -- Locked once identity checking has started or finished.
    IF EXISTS (SELECT 1 FROM xera_kyc WHERE user_id = p_user_id AND status IN ('VERIFIED', 'PENDING')) THEN
        RAISE EXCEPTION 'kyc_locked' USING ERRCODE = 'P0502';
    END IF;

    -- Lock the wallet: this also serialises two name changes by the same person.
    SELECT * INTO v_w FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet_not_found' USING ERRCODE = 'P0007';
    END IF;
    IF v_w.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'wallet_not_active' USING ERRCODE = 'P0001';
    END IF;

    -- Re-check idempotency now that the wallet is locked.
    SELECT * INTO v_existing FROM xera_name_changes WHERE request_id = p_request_id;
    IF FOUND THEN
        RETURN v_existing;
    END IF;

    SELECT COUNT(*) INTO v_used FROM xera_name_changes WHERE user_id = p_user_id;
    SELECT COALESCE(extra_slots, 0) INTO v_extra FROM xera_name_change_allowance WHERE user_id = p_user_id;
    IF v_used >= v_cfg.max_changes + COALESCE(v_extra, 0) THEN
        RAISE EXCEPTION 'no_change_left' USING ERRCODE = 'P0503';
    END IF;

    IF v_cfg.fee > 0 AND xera_discount_spendable(p_user_id) < v_cfg.fee THEN
        RAISE EXCEPTION 'insufficient_balance' USING ERRCODE = 'P0010';
    END IF;

    INSERT INTO xera_name_changes (request_id, user_id, old_name, new_name, fee_amount)
    VALUES (p_request_id, p_user_id, v_old, v_new, v_cfg.fee)
    RETURNING * INTO v_row;

    IF v_cfg.fee > 0 THEN
        INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
        VALUES (v_w.id, p_user_id, 'NAME_CHANGE_FEE', v_cfg.fee, 'DEBIT', 'namechange:' || v_row.id,
                jsonb_build_object('name_change_id', v_row.id));
        UPDATE xera_wallets SET cached_balance = cached_balance - v_cfg.fee, updated_at = now() WHERE id = v_w.id;
    END IF;

    UPDATE users SET full_name = v_new WHERE id = p_user_id;

    RETURN v_row;
END;
$$;

-- 6. look-only fee total for the admin Vaults tab
CREATE OR REPLACE FUNCTION xera_name_change_fee_summary() RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT jsonb_build_object(
        'total_fees',     COALESCE(SUM(fee_amount), 0),
        'fees_last_30d',  COALESCE(SUM(fee_amount) FILTER (WHERE created_at > now() - interval '30 days'), 0),
        'changes',        COUNT(*)
    ) FROM xera_name_changes;
$$;

-- 7. LOCK-DOWN: service_role (backend) only
ALTER TABLE xera_name_change_config    ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_name_changes          ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_name_change_allowance ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON xera_name_change_config, xera_name_changes, xera_name_change_allowance FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON xera_name_change_config, xera_name_change_allowance TO service_role;
GRANT SELECT ON xera_name_changes TO service_role;
GRANT USAGE, SELECT ON SEQUENCE xera_name_changes_id_seq TO service_role;
REVOKE ALL ON FUNCTION xera_change_name(BIGINT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION xera_name_change_fee_summary()       FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION xera_change_name(BIGINT, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION xera_name_change_fee_summary()       TO service_role;

COMMIT;

-- Check:
--   SELECT * FROM xera_name_change_config;
--   Change the fee later:   UPDATE xera_name_change_config SET fee = 150 WHERE id = 1;
--   Pause name changes:     UPDATE xera_name_change_config SET enabled = false WHERE id = 1;
