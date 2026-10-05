-- ============================================================
-- XERA: wallet connection methods (connected vs manual)
--
-- Reuses xera_external_wallets — NO new wallet table. Adds:
--   1. connection_method  'wallet' (signature-verified) | 'manual' (typed address)
--   2. DB-level guarantee that a manual address can NEVER be VERIFIED
--   3. one active manual address per (user, chain)
--   4. case-insensitive uniqueness of VERIFIED addresses
--   5. xera_set_manual_wallet / xera_remove_external_wallet RPCs
--   6. xera_link_external_wallet now also retires a superseded manual row
--
-- Representation:
--   connected wallet : status='VERIFIED', connection_method='wallet', verified_at set
--   manual address   : status='PENDING',  connection_method='manual', verified_at NULL
-- The claim path (python/xera/chain/claims.py) only ever reads status='VERIFIED',
-- so a manual address can be displayed and stored but can never settle a claim.
--
-- Apply AFTER 20260912 and 20260914. Safe to re-run.
-- ============================================================

-- ------------------------------------------------------------
-- 1. COLUMN + CONSTRAINTS
-- ------------------------------------------------------------

ALTER TABLE xera_external_wallets
    ADD COLUMN IF NOT EXISTS connection_method TEXT NOT NULL DEFAULT 'wallet';

DO $$
BEGIN
    ALTER TABLE xera_external_wallets
        ADD CONSTRAINT xera_ext_wallet_connection_method_chk
        CHECK (connection_method IN ('wallet', 'manual'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Even a bug (or a hand-written UPDATE) cannot promote a typed address to
-- "verified ownership". Ownership requires the signature path, which writes
-- connection_method = 'wallet'.
DO $$
BEGIN
    ALTER TABLE xera_external_wallets
        ADD CONSTRAINT xera_ext_wallet_manual_never_verified_chk
        CHECK (connection_method <> 'manual' OR status <> 'VERIFIED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- At most one ACTIVE manual address per user+chain. Replaced/revoked rows
-- drop out of the index.
CREATE UNIQUE INDEX IF NOT EXISTS xera_one_active_manual_wallet_per_chain
    ON xera_external_wallets(user_id, chain)
    WHERE status = 'PENDING' AND connection_method = 'manual';

-- The original unique index on (chain, address) is case-sensitive. BNB
-- addresses compare case-insensitively, so two spellings of one address could
-- have been linked by two accounts. Add a case-insensitive twin. Wrapped so
-- that pre-existing duplicate data (none expected) can never abort the whole
-- migration — it is reported instead.
DO $$
BEGIN
    CREATE UNIQUE INDEX IF NOT EXISTS xera_wallet_address_unique_active_ci
        ON xera_external_wallets(chain, lower(address))
        WHERE status = 'VERIFIED';
EXCEPTION WHEN unique_violation THEN
    RAISE NOTICE 'xera_wallet_address_unique_active_ci NOT created: duplicate verified addresses exist (differing only by case). Resolve them, then re-run this migration.';
END $$;

-- ------------------------------------------------------------
-- 2. SET / REPLACE A MANUAL ADDRESS
-- ------------------------------------------------------------
-- Never touches the cooldown table: a manual address proves nothing and
-- confers no claim rights, so there is nothing to rate-limit.
-- Refuses while a VERIFIED wallet exists on that chain — the user must
-- disconnect it first, so the UI never shows two competing "wallets".

CREATE OR REPLACE FUNCTION xera_set_manual_wallet(
    p_user_id  BIGINT,
    p_chain    TEXT,
    p_address  TEXT
) RETURNS xera_external_wallets
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_new xera_external_wallets;
BEGIN
    IF p_chain NOT IN ('BNB', 'TON') THEN
        RAISE EXCEPTION 'invalid_chain' USING ERRCODE = 'P0101';
    END IF;

    IF EXISTS (
        SELECT 1 FROM xera_external_wallets
        WHERE user_id = p_user_id AND chain = p_chain AND status = 'VERIFIED'
    ) THEN
        RAISE EXCEPTION 'verified_wallet_exists' USING ERRCODE = 'P0130';
    END IF;

    UPDATE xera_external_wallets
        SET status = 'REPLACED', replaced_at = now(), updated_at = now()
        WHERE user_id = p_user_id AND chain = p_chain
          AND status = 'PENDING' AND connection_method = 'manual';

    BEGIN
        INSERT INTO xera_external_wallets
            (user_id, chain, address, is_primary, status, connection_method, verified_at)
        VALUES
            (p_user_id, p_chain, p_address, true, 'PENDING', 'manual', NULL)
        RETURNING * INTO v_new;
    EXCEPTION WHEN unique_violation THEN
        -- Two concurrent "add" requests from the same user.
        RAISE EXCEPTION 'manual_wallet_conflict' USING ERRCODE = 'P0132';
    END;

    RETURN v_new;
END;
$$;

-- ------------------------------------------------------------
-- 3. REMOVE / DISCONNECT
-- ------------------------------------------------------------
-- Removes the user's ACTIVE wallet for a chain (manual or verified). Rows are
-- never deleted — status becomes REVOKED so history stays auditable, and
-- existing on-chain claim reservations (which store their own wallet_address)
-- are unaffected.
--
-- Disconnecting a VERIFIED wallet stamps the change-cooldown exactly like a
-- replacement does. Otherwise "disconnect, then immediately link a different
-- wallet" would be a way around xera_link_external_wallet's cooldown.

CREATE OR REPLACE FUNCTION xera_remove_external_wallet(
    p_user_id  BIGINT,
    p_chain    TEXT
) RETURNS xera_external_wallets
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row xera_external_wallets;
BEGIN
    IF p_chain NOT IN ('BNB', 'TON') THEN
        RAISE EXCEPTION 'invalid_chain' USING ERRCODE = 'P0101';
    END IF;

    UPDATE xera_external_wallets
        SET status = 'REVOKED', replaced_at = now(), updated_at = now()
        WHERE user_id = p_user_id AND chain = p_chain
          AND status IN ('VERIFIED', 'PENDING')
        RETURNING * INTO v_row;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'wallet_not_found' USING ERRCODE = 'P0131';
    END IF;

    IF v_row.connection_method = 'wallet' THEN
        INSERT INTO xera_wallet_cooldowns (user_id, chain, last_changed_at)
        VALUES (p_user_id, p_chain, now())
        ON CONFLICT (user_id, chain) DO UPDATE SET last_changed_at = now();
    END IF;

    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 3b. LINK (verified) — now also retires a superseded manual address
-- ------------------------------------------------------------
-- Identical to the original (20260912) except for the extra UPDATE retiring
-- the manual row and the explicit connection_method = 'wallet'.

CREATE OR REPLACE FUNCTION xera_link_external_wallet(
    p_user_id           BIGINT,
    p_chain             TEXT,
    p_address           TEXT,
    p_cooldown_seconds  INTEGER
) RETURNS xera_external_wallets
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_existing  xera_external_wallets;
    v_cooldown  xera_wallet_cooldowns;
    v_new       xera_external_wallets;
BEGIN
    IF p_chain NOT IN ('BNB', 'TON') THEN
        RAISE EXCEPTION 'invalid_chain' USING ERRCODE = 'P0101';
    END IF;

    SELECT * INTO v_cooldown FROM xera_wallet_cooldowns WHERE user_id = p_user_id AND chain = p_chain FOR UPDATE;
    IF FOUND AND v_cooldown.last_changed_at + make_interval(secs => p_cooldown_seconds) > now() THEN
        RAISE EXCEPTION 'wallet_change_cooldown_active' USING ERRCODE = 'P0105';
    END IF;

    SELECT * INTO v_existing
        FROM xera_external_wallets
        WHERE user_id = p_user_id AND chain = p_chain AND status = 'VERIFIED'
        FOR UPDATE;

    IF FOUND THEN
        UPDATE xera_external_wallets
            SET status = 'REPLACED', replaced_at = now(), updated_at = now()
            WHERE id = v_existing.id;
    END IF;

    -- A typed address is superseded by a signature-verified one.
    UPDATE xera_external_wallets
        SET status = 'REPLACED', replaced_at = now(), updated_at = now()
        WHERE user_id = p_user_id AND chain = p_chain
          AND status = 'PENDING' AND connection_method = 'manual';

    BEGIN
        INSERT INTO xera_external_wallets (user_id, chain, address, is_primary, status, connection_method, verified_at)
        VALUES (p_user_id, p_chain, p_address, true, 'VERIFIED', 'wallet', now())
        RETURNING * INTO v_new;
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'address_already_linked' USING ERRCODE = 'P0106';
    END;

    INSERT INTO xera_wallet_cooldowns (user_id, chain, last_changed_at)
    VALUES (p_user_id, p_chain, now())
    ON CONFLICT (user_id, chain) DO UPDATE SET last_changed_at = now();

    RETURN v_new;
END;
$$;

-- ------------------------------------------------------------
-- 4. PRIVILEGES — same default-deny model as 20260914 section 4
-- ------------------------------------------------------------
REVOKE EXECUTE ON FUNCTION xera_set_manual_wallet(BIGINT, TEXT, TEXT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_remove_external_wallet(BIGINT, TEXT) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION xera_set_manual_wallet(BIGINT, TEXT, TEXT) TO service_role;
GRANT  EXECUTE ON FUNCTION xera_remove_external_wallet(BIGINT, TEXT) TO service_role;
-- xera_link_external_wallet keeps the REVOKE/GRANT from 20260914
-- (CREATE OR REPLACE preserves existing privileges).
