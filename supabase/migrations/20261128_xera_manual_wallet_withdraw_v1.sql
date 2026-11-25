-- ============================================================
-- XERA: withdraw to a manually added wallet address (BNB)
--
-- Changes to xera_set_manual_wallet:
--   1. One address, one account: a typed address that another account already
--      uses (verified, or typed by someone else) is refused: address_already_linked.
--   2. Saving the SAME address again does nothing (the waiting period is not reset).
--      Saving a DIFFERENT address starts a new row, so the waiting period starts again.
--
-- Also adds a unique index so two accounts can never hold the same typed address,
-- even if two requests race each other.
--
-- The waiting period itself (default 12 hours) and the password check are enforced
-- by the backend (xera/chain/claims.py, xera/routes_chain.py). linked_at on the manual
-- row is the start of the waiting period, so no new column is needed.
--
-- Apply after 20261003. Safe to run twice. Drops nothing.
-- ============================================================

DO $$
BEGIN
    CREATE UNIQUE INDEX IF NOT EXISTS xera_manual_wallet_address_unique_active_ci
        ON xera_external_wallets(chain, lower(address))
        WHERE status = 'PENDING' AND connection_method = 'manual';
EXCEPTION WHEN unique_violation THEN
    RAISE NOTICE 'xera_manual_wallet_address_unique_active_ci NOT created: two accounts already hold the same typed address. Resolve them, then re-run this migration.';
END $$;

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
    v_new      xera_external_wallets;
    v_current  xera_external_wallets;
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

    -- One address, one account.
    IF EXISTS (
        SELECT 1 FROM xera_external_wallets
        WHERE chain = p_chain AND lower(address) = lower(p_address)
          AND user_id <> p_user_id
          AND (status = 'VERIFIED' OR (status = 'PENDING' AND connection_method = 'manual'))
    ) THEN
        RAISE EXCEPTION 'address_already_linked' USING ERRCODE = 'P0106';
    END IF;

    -- Same address again: keep the existing row and its waiting period.
    SELECT * INTO v_current FROM xera_external_wallets
        WHERE user_id = p_user_id AND chain = p_chain
          AND status = 'PENDING' AND connection_method = 'manual'
          AND lower(address) = lower(p_address)
        LIMIT 1;
    IF FOUND THEN
        RETURN v_current;
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
        -- Either two requests from this user at once, or another account just took this address.
        IF EXISTS (
            SELECT 1 FROM xera_external_wallets
            WHERE chain = p_chain AND lower(address) = lower(p_address) AND user_id <> p_user_id
              AND status = 'PENDING' AND connection_method = 'manual'
        ) THEN
            RAISE EXCEPTION 'address_already_linked' USING ERRCODE = 'P0106';
        END IF;
        RAISE EXCEPTION 'manual_wallet_conflict' USING ERRCODE = 'P0132';
    END;

    RETURN v_new;
END;
$$;

REVOKE EXECUTE ON FUNCTION xera_set_manual_wallet(BIGINT, TEXT, TEXT) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION xera_set_manual_wallet(BIGINT, TEXT, TEXT) TO service_role;
