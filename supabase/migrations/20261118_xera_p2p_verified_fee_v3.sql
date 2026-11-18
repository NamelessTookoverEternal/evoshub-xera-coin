-- ============================================================
-- XERA P2P v3: small fee for fully verified senders (default 1%)
-- ============================================================
-- Run AFTER v1 and v2 (run once). Additive and re-runnable.
--   * Verified senders (every transfer step complete) now pay verified_fee_bps
--     on top of the amount (default 100 = 1%). Unverified senders still pay
--     unverified_fee_bps (default 5000 = 50%). Recipient always gets the full amount.
--   * Fees go to the look-only fee vault (xera_p2p_fee_vault_summary); no wallet holds them.
--   * Same function signature as v2, so existing grants stay in place.
-- ============================================================

BEGIN;

ALTER TABLE xera_p2p_config
    ADD COLUMN IF NOT EXISTS verified_fee_bps INTEGER NOT NULL DEFAULT 100;   -- 100 = 1%

ALTER TABLE xera_p2p_config DROP CONSTRAINT IF EXISTS xera_p2p_cfg_v3_check;
ALTER TABLE xera_p2p_config ADD CONSTRAINT xera_p2p_cfg_v3_check CHECK (
    verified_fee_bps BETWEEN 0 AND 10000 AND verified_fee_bps <= unverified_fee_bps
);

CREATE OR REPLACE FUNCTION xera_p2p_transfer(
    p_sender_user_id     BIGINT,
    p_recipient_xera_id  TEXT,
    p_amount             NUMERIC,
    p_request_id         TEXT,
    p_sender_verified    BOOLEAN,           -- decided by the backend (all transfer steps complete?)
    p_ip_address         TEXT,              -- client IP seen by the backend (may be NULL)
    p_ip_risk            JSONB              -- result of the IP check (may be NULL)
) RETURNS xera_p2p_transfers
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_cfg        xera_p2p_config;
    v_sys        xera_config;
    v_existing   xera_p2p_transfers;
    v_recipient  BIGINT;
    v_sender_xid TEXT;
    v_recip_xid  TEXT;
    v_sw         xera_wallets;
    v_rw         xera_wallets;
    v_sent_24h   NUMERIC;
    v_daily_cap  NUMERIC;
    v_fee        NUMERIC(20,4);
    v_fee_bps    INTEGER;
    v_row        xera_p2p_transfers;
BEGIN
    IF p_amount IS NULL OR p_amount <= 0 OR p_request_id IS NULL OR btrim(p_request_id) = ''
       OR p_sender_verified IS NULL THEN
        RAISE EXCEPTION 'invalid_amount' USING ERRCODE = 'P0009';
    END IF;
    p_amount := round(p_amount, 4);

    SELECT * INTO v_existing FROM xera_p2p_transfers WHERE request_id = p_request_id;
    IF FOUND THEN
        IF v_existing.sender_user_id <> p_sender_user_id THEN
            RAISE EXCEPTION 'request_id_conflict' USING ERRCODE = 'P0407';
        END IF;
        RETURN v_existing;
    END IF;

    SELECT * INTO v_sys FROM xera_config WHERE id = 1;
    IF NOT COALESCE(v_sys.system_enabled, false) OR NOT COALESCE(v_sys.transfer_enabled, false) THEN
        RAISE EXCEPTION 'transfers_disabled' USING ERRCODE = 'P0402';
    END IF;

    SELECT * INTO v_cfg FROM xera_p2p_config WHERE id = 1;
    IF p_amount < v_cfg.min_amount OR p_amount > v_cfg.max_amount THEN
        RAISE EXCEPTION 'amount_out_of_range' USING ERRCODE = 'P0405';
    END IF;

    -- Fee + cap depend on whether the sender completed every step.
    IF p_sender_verified THEN
        v_fee_bps := v_cfg.verified_fee_bps;
        v_daily_cap := v_cfg.daily_max_total;
    ELSE
        v_fee_bps := v_cfg.unverified_fee_bps;
        v_daily_cap := v_cfg.unverified_daily_max;
    END IF;
    v_fee := round(p_amount * v_fee_bps / 10000.0, 4);

    SELECT id, xera_id INTO v_recipient, v_recip_xid
      FROM users WHERE xera_id = upper(btrim(p_recipient_xera_id));
    IF v_recipient IS NULL THEN
        RAISE EXCEPTION 'recipient_not_found' USING ERRCODE = 'P0403';
    END IF;
    IF v_recipient = p_sender_user_id THEN
        RAISE EXCEPTION 'self_transfer' USING ERRCODE = 'P0404';
    END IF;

    v_sender_xid := xera_ensure_xera_id(p_sender_user_id);

    INSERT INTO xera_wallets (user_id) VALUES (v_recipient) ON CONFLICT (user_id) DO NOTHING;

    PERFORM 1 FROM xera_wallets
     WHERE user_id IN (p_sender_user_id, v_recipient)
     ORDER BY id FOR UPDATE;

    SELECT * INTO v_sw FROM xera_wallets WHERE user_id = p_sender_user_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet_not_found' USING ERRCODE = 'P0007';
    END IF;
    SELECT * INTO v_rw FROM xera_wallets WHERE user_id = v_recipient;

    IF v_sw.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'wallet_not_active' USING ERRCODE = 'P0001';
    END IF;
    IF v_rw.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'recipient_not_active' USING ERRCODE = 'P0408';
    END IF;

    SELECT * INTO v_existing FROM xera_p2p_transfers WHERE request_id = p_request_id;
    IF FOUND THEN
        IF v_existing.sender_user_id <> p_sender_user_id THEN
            RAISE EXCEPTION 'request_id_conflict' USING ERRCODE = 'P0407';
        END IF;
        RETURN v_existing;
    END IF;

    -- Rolling 24h total of AMOUNTS sent (fees don't count toward the cap).
    SELECT COALESCE(SUM(amount), 0) INTO v_sent_24h
      FROM xera_p2p_transfers
     WHERE sender_user_id = p_sender_user_id AND created_at > now() - interval '24 hours';
    IF v_sent_24h + p_amount > v_daily_cap THEN
        RAISE EXCEPTION 'daily_limit_exceeded' USING ERRCODE = 'P0406';
    END IF;

    -- Spendable must cover the amount AND the fee.
    IF xera_discount_spendable(p_sender_user_id) < p_amount + v_fee THEN
        RAISE EXCEPTION 'insufficient_balance' USING ERRCODE = 'P0010';
    END IF;

    INSERT INTO xera_p2p_transfers (request_id, sender_user_id, recipient_user_id,
                                    sender_xera_id, recipient_xera_id, amount,
                                    fee_amount, sender_verified, ip_address, ip_risk)
    VALUES (p_request_id, p_sender_user_id, v_recipient,
            v_sender_xid, v_recip_xid, p_amount,
            v_fee, p_sender_verified, NULLIF(btrim(p_ip_address), ''), p_ip_risk)
    RETURNING * INTO v_row;

    INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
    VALUES (v_sw.id, p_sender_user_id, 'P2P_SEND', p_amount, 'DEBIT', 'p2p:' || v_row.id,
            jsonb_build_object('transfer_id', v_row.id, 'counterparty_xera_id', v_recip_xid));

    IF v_fee > 0 THEN
        INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
        VALUES (v_sw.id, p_sender_user_id, 'P2P_FEE', v_fee, 'DEBIT', 'p2p:' || v_row.id,
                jsonb_build_object('transfer_id', v_row.id, 'fee_bps', v_fee_bps));
    END IF;

    INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
    VALUES (v_rw.id, v_recipient, 'P2P_RECEIVE', p_amount, 'CREDIT', 'p2p:' || v_row.id,
            jsonb_build_object('transfer_id', v_row.id, 'counterparty_xera_id', v_sender_xid));

    UPDATE xera_wallets SET cached_balance = cached_balance - (p_amount + v_fee), updated_at = now() WHERE id = v_sw.id;
    UPDATE xera_wallets SET cached_balance = cached_balance + p_amount,           updated_at = now() WHERE id = v_rw.id;

    RETURN v_row;
END;
$$;

COMMIT;

-- Verify after running:
--   SELECT verified_fee_bps, unverified_fee_bps FROM xera_p2p_config;   -- 100 / 5000
