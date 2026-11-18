-- ============================================================
-- XERA P2P v2: fee for senders who haven't completed all steps,
--              IP + VPN record, and the "suspicious recipient" review
-- ============================================================
-- Run AFTER 20261116_xera_p2p_v1.sql. Additive and re-runnable.
--
-- WHAT THIS DOES
--   1. A sender who has NOT completed every transfer step (identity check
--      + first-transfer fee) may still send, but pays a fee on top
--      (default 50% of the amount) and has a lower daily cap (default 100).
--      Fully verified senders pay nothing, as before.
--      The recipient always receives the full amount.
--   2. The fee is NOT paid to any wallet. Like the discount vault, it is
--      debited from the sender, recorded in the ledger as P2P_FEE, and shown
--      as a look-only total (xera_p2p_fee_vault_summary). Nothing is returned
--      to the 75M mining pool and no allocation number is touched.
--   3. Every transfer now stores the sender's verification state, the IP
--      address and an IP-risk note (VPN / proxy flag when a checker is set up).
--   4. xera_p2p_flagged(): wallets that received XERA from several accounts
--      that hadn't completed verification, or from accounts sharing one IP.
--
-- DOES NOT TOUCH: on-chain claims, withdrawals, mining, referrals, KYC code.
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. CONFIG
-- ------------------------------------------------------------
ALTER TABLE xera_p2p_config
    ADD COLUMN IF NOT EXISTS unverified_fee_bps     INTEGER       NOT NULL DEFAULT 5000,   -- 5000 = 50%
    ADD COLUMN IF NOT EXISTS unverified_daily_max   NUMERIC(20,4) NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS flag_min_senders       INTEGER       NOT NULL DEFAULT 3,
    ADD COLUMN IF NOT EXISTS flag_window_days       INTEGER       NOT NULL DEFAULT 7;

ALTER TABLE xera_p2p_config DROP CONSTRAINT IF EXISTS xera_p2p_cfg_v2_check;
ALTER TABLE xera_p2p_config ADD CONSTRAINT xera_p2p_cfg_v2_check CHECK (
    unverified_fee_bps BETWEEN 0 AND 10000
    AND unverified_daily_max >= max_amount
    AND unverified_daily_max <= daily_max_total
    AND flag_min_senders >= 2
    AND flag_window_days BETWEEN 1 AND 90
);

-- ------------------------------------------------------------
-- 2. TRANSFER RECORD: fee, verification state, IP, IP risk
-- ------------------------------------------------------------
ALTER TABLE xera_p2p_transfers
    ADD COLUMN IF NOT EXISTS fee_amount      NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK (fee_amount >= 0),
    ADD COLUMN IF NOT EXISTS sender_verified BOOLEAN,
    ADD COLUMN IF NOT EXISTS ip_address      TEXT,
    ADD COLUMN IF NOT EXISTS ip_risk         JSONB;   -- e.g. {"vpn": true, "provider": "proxycheck", "type": "VPN"}; {"vpn": null} = not checked

CREATE INDEX IF NOT EXISTS idx_xera_p2p_recipient_time ON xera_p2p_transfers (recipient_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_xera_p2p_ip ON xera_p2p_transfers (ip_address) WHERE ip_address IS NOT NULL;

-- ------------------------------------------------------------
-- 3. LEDGER TYPE for the fee
-- ------------------------------------------------------------
ALTER TABLE xera_transactions DROP CONSTRAINT IF EXISTS xera_transactions_type_check;
ALTER TABLE xera_transactions ADD CONSTRAINT xera_transactions_type_check CHECK (type IN (
    'MINING_REWARD','XERA_PURCHASE','REFERRAL_REWARD','BONUS','DAILY_CLAIM',
    'ADMIN_CREDIT','ADMIN_DEBIT','REVERSAL','MIGRATION','ONCHAIN_CLAIM','DISCOUNT_SPEND',
    'P2P_SEND','P2P_RECEIVE','P2P_FEE'
));
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_p2p_fee_unique
    ON xera_transactions (reference_id) WHERE type = 'P2P_FEE';

-- ------------------------------------------------------------
-- 4. THE TRANSFER (replaces the v1 function; new signature)
--    New error codes: P0409 invalid_fee
-- ------------------------------------------------------------
DROP FUNCTION IF EXISTS xera_p2p_transfer(BIGINT, TEXT, NUMERIC, TEXT);

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
        v_fee := 0;
        v_daily_cap := v_cfg.daily_max_total;
    ELSE
        v_fee := round(p_amount * v_cfg.unverified_fee_bps / 10000.0, 4);
        v_daily_cap := v_cfg.unverified_daily_max;
    END IF;

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
                jsonb_build_object('transfer_id', v_row.id, 'fee_bps', v_cfg.unverified_fee_bps));
    END IF;

    INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
    VALUES (v_rw.id, v_recipient, 'P2P_RECEIVE', p_amount, 'CREDIT', 'p2p:' || v_row.id,
            jsonb_build_object('transfer_id', v_row.id, 'counterparty_xera_id', v_sender_xid));

    UPDATE xera_wallets SET cached_balance = cached_balance - (p_amount + v_fee), updated_at = now() WHERE id = v_sw.id;
    UPDATE xera_wallets SET cached_balance = cached_balance + p_amount,           updated_at = now() WHERE id = v_rw.id;

    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 5. LOOK-ONLY FEE TOTAL (same idea as the discount vault; moves nothing)
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION xera_p2p_fee_vault_summary()
RETURNS JSONB
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT jsonb_build_object(
        'total_fees',        COALESCE(SUM(fee_amount), 0),
        'fees_last_30d',     COALESCE(SUM(fee_amount) FILTER (WHERE created_at > now() - interval '30 days'), 0),
        'transfers_total',   COUNT(*),
        'transfers_with_fee', COUNT(*) FILTER (WHERE fee_amount > 0),
        'volume_total',      COALESCE(SUM(amount), 0)
    )
    FROM xera_p2p_transfers;
$$;

-- ------------------------------------------------------------
-- 6. SUSPICIOUS RECIPIENTS
--    A wallet is flagged when, inside the window, it received XERA from
--      (a) at least flag_min_senders DIFFERENT accounts that had not completed
--          verification, or
--      (b) 2+ different sender accounts that used the same IP address.
--    It also reports how many of its transfers came from a VPN/proxy IP.
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION xera_p2p_flagged(p_min_senders INTEGER DEFAULT NULL, p_days INTEGER DEFAULT NULL)
RETURNS TABLE (
    recipient_user_id    BIGINT,
    recipient_xera_id    TEXT,
    distinct_senders     BIGINT,
    unverified_senders   BIGINT,
    senders_sharing_ip   BIGINT,
    vpn_transfers        BIGINT,
    transfers            BIGINT,
    total_amount         NUMERIC,
    first_at             TIMESTAMPTZ,
    last_at              TIMESTAMPTZ,
    reasons              TEXT[]
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_cfg  xera_p2p_config;
    v_min  INTEGER;
    v_days INTEGER;
BEGIN
    SELECT * INTO v_cfg FROM xera_p2p_config WHERE id = 1;
    v_min  := COALESCE(p_min_senders, v_cfg.flag_min_senders);
    v_days := COALESCE(p_days,        v_cfg.flag_window_days);

    RETURN QUERY
    WITH win AS (
        SELECT * FROM xera_p2p_transfers WHERE created_at > now() - make_interval(days => v_days)
    ),
    shared_ip AS (   -- per recipient: IPs used by 2+ different senders
        SELECT w.recipient_user_id AS rid, w.ip_address
          FROM win w
         WHERE w.ip_address IS NOT NULL
         GROUP BY w.recipient_user_id, w.ip_address
        HAVING COUNT(DISTINCT w.sender_user_id) > 1
    ),
    agg AS (
        SELECT w.recipient_user_id AS rid,
               MAX(w.recipient_xera_id) AS rxid,
               COUNT(DISTINCT w.sender_user_id) AS senders,
               COUNT(DISTINCT w.sender_user_id) FILTER (WHERE w.sender_verified IS NOT TRUE) AS unv,
               COUNT(DISTINCT w.sender_user_id) FILTER (
                   WHERE EXISTS (SELECT 1 FROM shared_ip s WHERE s.rid = w.recipient_user_id AND s.ip_address = w.ip_address)
               ) AS sharing,
               COUNT(*) FILTER (WHERE (w.ip_risk ->> 'vpn') = 'true') AS vpn,
               COUNT(*) AS n,
               SUM(w.amount) AS total,
               MIN(w.created_at) AS first_at,
               MAX(w.created_at) AS last_at
          FROM win w
         GROUP BY w.recipient_user_id
    )
    SELECT a.rid, a.rxid, a.senders, a.unv, a.sharing, a.vpn, a.n, a.total, a.first_at, a.last_at,
           ARRAY_REMOVE(ARRAY[
               CASE WHEN a.unv >= v_min THEN 'multiple_unverified_senders' END,
               CASE WHEN a.sharing >= 2 THEN 'senders_share_ip' END
           ], NULL)
      FROM agg a
     WHERE a.unv >= v_min OR a.sharing >= 2
     ORDER BY a.unv DESC, a.sharing DESC, a.last_at DESC;
END;
$$;

-- ------------------------------------------------------------
-- 7. LOCK-DOWN (service_role / backend only)
-- ------------------------------------------------------------
REVOKE EXECUTE ON FUNCTION xera_p2p_transfer(BIGINT, TEXT, NUMERIC, TEXT, BOOLEAN, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION xera_p2p_fee_vault_summary()   FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION xera_p2p_flagged(INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION xera_p2p_transfer(BIGINT, TEXT, NUMERIC, TEXT, BOOLEAN, TEXT, JSONB) TO service_role;
GRANT  EXECUTE ON FUNCTION xera_p2p_fee_vault_summary()   TO service_role;
GRANT  EXECUTE ON FUNCTION xera_p2p_flagged(INTEGER, INTEGER) TO service_role;

COMMIT;

-- ------------------------------------------------------------
-- Verify after running:
--   SELECT unverified_fee_bps, unverified_daily_max, flag_min_senders, flag_window_days FROM xera_p2p_config;  -- 5000 / 100 / 3 / 7
--   SELECT xera_p2p_fee_vault_summary();
--   SELECT * FROM xera_p2p_flagged();            -- empty at first
-- ------------------------------------------------------------
