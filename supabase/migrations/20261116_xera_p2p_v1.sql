-- ============================================================
-- XERA: in-app P2P transfers (XERA user -> XERA user)
-- ============================================================
-- WHAT THIS DOES
--   1. Gives every user a short XERA ID (users.xera_id, e.g. XR-7K4M9P2Q)
--      that is used ONLY for P2P. Invite/referral codes are not touched.
--   2. Adds xera_p2p_config   (min / max per transfer / daily total).
--   3. Adds xera_p2p_transfers (append-only record of every transfer) and
--      xera_p2p_public_ledger (read-only view with MASKED XERA IDs only).
--   4. Adds ledger types P2P_SEND and P2P_RECEIVE (all existing types kept).
--   5. Adds xera_p2p_transfer(): the ONLY way a P2P transfer moves balance.
--      It locks both wallets (lowest id first, no deadlock), debits the
--      sender, credits the recipient, writes two ledger rows + one transfer
--      row, and is idempotent on request_id.
--
-- WHAT THIS DOES NOT TOUCH
--   On-chain claims, withdrawal to external wallets, mining, referrals,
--   KYC, the transfer fee, xera_claimable_balance, allocations.
--   A P2P transfer moves existing in-app balance only: nothing is minted,
--   so mining_distributed / entitlement caps are unchanged.
--
-- DEPENDS ON: 20261107_xera_data_discount_v1.sql (xera_discount_spendable,
--   so tokens held for a pending data order cannot be sent).
--
-- GATES (enforced in the DB function AND by the backend):
--   xera_config.system_enabled and xera_config.transfer_enabled (default OFF).
--   KYC + first-transfer fee for the sender are checked by the backend
--   (python/xera/readiness.require_transfer_ready) before calling this.
--
-- Additive, re-runnable. Run in Supabase SQL Editor (production).
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. XERA ID
-- ------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS xera_id TEXT;

-- Alphabet without look-alikes (no 0/O, 1/I/L) to cut mistyped IDs.
CREATE OR REPLACE FUNCTION xera_generate_xera_id()
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    v_alphabet CONSTANT TEXT := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
    v_id  TEXT;
    i     INTEGER;
BEGIN
    LOOP
        v_id := 'XR-';
        FOR i IN 1..8 LOOP
            v_id := v_id || substr(v_alphabet, 1 + floor(random() * length(v_alphabet))::int, 1);
        END LOOP;
        EXIT WHEN NOT EXISTS (SELECT 1 FROM users WHERE xera_id = v_id);
    END LOOP;
    RETURN v_id;
END;
$$;

-- Backfill existing users once.
UPDATE users SET xera_id = xera_generate_xera_id() WHERE xera_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS users_xera_id_key ON users (xera_id) WHERE xera_id IS NOT NULL;

-- New users get theirs lazily: the backend calls this before showing / using an ID.
CREATE OR REPLACE FUNCTION xera_ensure_xera_id(p_user_id BIGINT)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_id TEXT;
BEGIN
    SELECT xera_id INTO v_id FROM users WHERE id = p_user_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'user_not_found' USING ERRCODE = 'P0401';
    END IF;
    IF v_id IS NULL THEN
        UPDATE users SET xera_id = xera_generate_xera_id()
         WHERE id = p_user_id AND xera_id IS NULL
        RETURNING xera_id INTO v_id;
        IF v_id IS NULL THEN  -- a concurrent call set it first
            SELECT xera_id INTO v_id FROM users WHERE id = p_user_id;
        END IF;
    END IF;
    RETURN v_id;
END;
$$;

-- ------------------------------------------------------------
-- 2. CONFIG (singleton)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_p2p_config (
    id               SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    min_amount       NUMERIC(20,4) NOT NULL DEFAULT 10   CHECK (min_amount > 0),
    max_amount       NUMERIC(20,4) NOT NULL DEFAULT 100  CHECK (max_amount >= min_amount),
    daily_max_total  NUMERIC(20,4) NOT NULL DEFAULT 500  CHECK (daily_max_total >= max_amount),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by       BIGINT REFERENCES users(id)
);
INSERT INTO xera_p2p_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ------------------------------------------------------------
-- 3. TRANSFERS (append-only)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_p2p_transfers (
    id                 BIGSERIAL PRIMARY KEY,
    request_id         TEXT NOT NULL UNIQUE,          -- client-generated; retry-safe
    sender_user_id     BIGINT NOT NULL REFERENCES users(id),
    recipient_user_id  BIGINT NOT NULL REFERENCES users(id),
    sender_xera_id     TEXT NOT NULL,
    recipient_xera_id  TEXT NOT NULL,
    amount             NUMERIC(20,4) NOT NULL CHECK (amount > 0),
    status             TEXT NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('COMPLETED')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT xera_p2p_no_self CHECK (sender_user_id <> recipient_user_id)
);
CREATE INDEX IF NOT EXISTS idx_xera_p2p_sender    ON xera_p2p_transfers (sender_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_xera_p2p_recipient ON xera_p2p_transfers (recipient_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_xera_p2p_created   ON xera_p2p_transfers (created_at DESC);

-- No edits, no deletes: a transfer record is permanent.
CREATE OR REPLACE FUNCTION xera_p2p_block_changes() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'xera_p2p_transfers is append-only' USING ERRCODE = 'P0420';
END;
$$;
DROP TRIGGER IF EXISTS xera_p2p_append_only ON xera_p2p_transfers;
CREATE TRIGGER xera_p2p_append_only
    BEFORE UPDATE OR DELETE ON xera_p2p_transfers
    FOR EACH ROW EXECUTE FUNCTION xera_p2p_block_changes();

-- Public, global ledger: masked IDs + amount + time. No names, no user ids.
CREATE OR REPLACE VIEW xera_p2p_public_ledger AS
SELECT t.id,
       left(t.sender_xera_id, 4)    || '…' || right(t.sender_xera_id, 3)    AS sender,
       left(t.recipient_xera_id, 4) || '…' || right(t.recipient_xera_id, 3) AS recipient,
       t.amount,
       t.status,
       t.created_at
  FROM xera_p2p_transfers t;

-- ------------------------------------------------------------
-- 4. LEDGER TYPES (keeps every existing type)
-- ------------------------------------------------------------
ALTER TABLE xera_transactions DROP CONSTRAINT IF EXISTS xera_transactions_type_check;
ALTER TABLE xera_transactions ADD CONSTRAINT xera_transactions_type_check CHECK (type IN (
    'MINING_REWARD','XERA_PURCHASE','REFERRAL_REWARD','BONUS','DAILY_CLAIM',
    'ADMIN_CREDIT','ADMIN_DEBIT','REVERSAL','MIGRATION','ONCHAIN_CLAIM','DISCOUNT_SPEND',
    'P2P_SEND','P2P_RECEIVE'
));

-- One send row and one receive row per transfer (idempotency backstop).
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_p2p_send_unique
    ON xera_transactions (reference_id) WHERE type = 'P2P_SEND';
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_p2p_receive_unique
    ON xera_transactions (reference_id) WHERE type = 'P2P_RECEIVE';

-- ------------------------------------------------------------
-- 5. THE TRANSFER (the only path that moves P2P balance)
--    Error codes: P0401 user_not_found, P0402 transfers_disabled,
--    P0403 recipient_not_found, P0404 self_transfer, P0405 amount_out_of_range,
--    P0406 daily_limit_exceeded, P0407 request_id_conflict,
--    P0408 recipient_not_active; plus existing P0001 wallet_not_active,
--    P0007 wallet_not_found, P0009 invalid_amount, P0010 insufficient_balance.
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION xera_p2p_transfer(
    p_sender_user_id     BIGINT,
    p_recipient_xera_id  TEXT,
    p_amount             NUMERIC,
    p_request_id         TEXT
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
    v_row        xera_p2p_transfers;
BEGIN
    IF p_amount IS NULL OR p_amount <= 0 OR p_request_id IS NULL OR btrim(p_request_id) = '' THEN
        RAISE EXCEPTION 'invalid_amount' USING ERRCODE = 'P0009';
    END IF;
    p_amount := round(p_amount, 4);

    -- Retry / double tap: same request id returns the original result, moves nothing.
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

    SELECT id, xera_id INTO v_recipient, v_recip_xid
      FROM users WHERE xera_id = upper(btrim(p_recipient_xera_id));
    IF v_recipient IS NULL THEN
        RAISE EXCEPTION 'recipient_not_found' USING ERRCODE = 'P0403';
    END IF;
    IF v_recipient = p_sender_user_id THEN
        RAISE EXCEPTION 'self_transfer' USING ERRCODE = 'P0404';
    END IF;

    v_sender_xid := xera_ensure_xera_id(p_sender_user_id);

    -- Make sure both wallets exist, then lock them in id order (no deadlock
    -- when two users send to each other at the same moment).
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

    -- Re-check idempotency now that the sender is locked (a concurrent twin
    -- of this request may have just committed).
    SELECT * INTO v_existing FROM xera_p2p_transfers WHERE request_id = p_request_id;
    IF FOUND THEN
        IF v_existing.sender_user_id <> p_sender_user_id THEN
            RAISE EXCEPTION 'request_id_conflict' USING ERRCODE = 'P0407';
        END IF;
        RETURN v_existing;
    END IF;

    -- Rolling 24h total. Safe against races: the sender's wallet row is locked.
    SELECT COALESCE(SUM(amount), 0) INTO v_sent_24h
      FROM xera_p2p_transfers
     WHERE sender_user_id = p_sender_user_id AND created_at > now() - interval '24 hours';
    IF v_sent_24h + p_amount > v_cfg.daily_max_total THEN
        RAISE EXCEPTION 'daily_limit_exceeded' USING ERRCODE = 'P0406';
    END IF;

    -- Spendable = balance minus tokens held for pending data orders.
    IF xera_discount_spendable(p_sender_user_id) < p_amount THEN
        RAISE EXCEPTION 'insufficient_balance' USING ERRCODE = 'P0010';
    END IF;

    INSERT INTO xera_p2p_transfers (request_id, sender_user_id, recipient_user_id,
                                    sender_xera_id, recipient_xera_id, amount)
    VALUES (p_request_id, p_sender_user_id, v_recipient, v_sender_xid, v_recip_xid, p_amount)
    RETURNING * INTO v_row;

    INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
    VALUES (v_sw.id, p_sender_user_id, 'P2P_SEND', p_amount, 'DEBIT', 'p2p:' || v_row.id,
            jsonb_build_object('transfer_id', v_row.id, 'counterparty_xera_id', v_recip_xid));

    INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
    VALUES (v_rw.id, v_recipient, 'P2P_RECEIVE', p_amount, 'CREDIT', 'p2p:' || v_row.id,
            jsonb_build_object('transfer_id', v_row.id, 'counterparty_xera_id', v_sender_xid));

    UPDATE xera_wallets SET cached_balance = cached_balance - p_amount, updated_at = now() WHERE id = v_sw.id;
    UPDATE xera_wallets SET cached_balance = cached_balance + p_amount, updated_at = now() WHERE id = v_rw.id;

    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 6. LOCK-DOWN: service_role (backend) only
-- ------------------------------------------------------------
ALTER TABLE xera_p2p_config    ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_p2p_transfers ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON xera_p2p_config, xera_p2p_transfers, xera_p2p_public_ledger FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON xera_p2p_config    TO service_role;
GRANT SELECT                 ON xera_p2p_transfers TO service_role;
GRANT SELECT                 ON xera_p2p_public_ledger TO service_role;
GRANT USAGE, SELECT ON SEQUENCE xera_p2p_transfers_id_seq TO service_role;

REVOKE EXECUTE ON FUNCTION xera_generate_xera_id()                        FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION xera_ensure_xera_id(BIGINT)                    FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION xera_p2p_transfer(BIGINT, TEXT, NUMERIC, TEXT) FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION xera_generate_xera_id()                        TO service_role;
GRANT  EXECUTE ON FUNCTION xera_ensure_xera_id(BIGINT)                    TO service_role;
GRANT  EXECUTE ON FUNCTION xera_p2p_transfer(BIGINT, TEXT, NUMERIC, TEXT) TO service_role;

COMMIT;

-- ------------------------------------------------------------
-- Verify after running:
--   SELECT count(*) FROM users WHERE xera_id IS NULL;            -- expect 0
--   SELECT * FROM xera_p2p_config;                                -- 10 / 100 / 500
--   SELECT * FROM xera_p2p_public_ledger LIMIT 5;                 -- empty at first
--   SELECT conname FROM pg_constraint WHERE conname = 'xera_transactions_type_check';
-- Transfers stay OFF until you set xera_config.transfer_enabled = true.
-- ------------------------------------------------------------
