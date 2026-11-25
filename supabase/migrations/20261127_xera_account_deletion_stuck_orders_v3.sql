-- ============================================================
-- Account deletion v3: a stuck EVOS Data order must not lock anyone out of deleting.
--
-- Some EVOS Data orders / agent withdrawals stay "paid", "processing" for a very long time (it can be a bug).
-- Before this file: that always blocked deletion. Now:
--   * 1st Delete press: the "in progress" notice is shown (as before).
--   * 2nd Delete press: the app sends continue_busy = true, the check ignores ONLY this one blocker,
--     and popup 2 (wallets + warnings) opens.
--   * The choice is saved on the deletion row (ignore_evosdata_busy), so day 7 does not wait for the stuck order either.
-- Every other blocker (suspended wallet, money lock, on-chain claim, XERA data order, KYC in review) still blocks.
--
-- Run AFTER 20261125 and 20261126. Safe to run twice. No existing function is dropped or changed in signature.
-- ============================================================

BEGIN;

ALTER TABLE xera_account_deletions ADD COLUMN IF NOT EXISTS ignore_evosdata_busy BOOLEAN NOT NULL DEFAULT false;

CREATE OR REPLACE FUNCTION xera_deletion_blocker_v3(p_user_id BIGINT, p_skip_busy BOOLEAN DEFAULT false) RETURNS TEXT
LANGUAGE plpgsql
STABLE
SET search_path = public
AS $$
DECLARE
    v_w      xera_wallets;
    v_locked BOOLEAN := false;
BEGIN
    SELECT * INTO v_w FROM xera_wallets WHERE user_id = p_user_id;
    IF v_w.id IS NOT NULL AND v_w.status <> 'ACTIVE' THEN
        RETURN 'wallet_not_active';
    END IF;

    IF to_regclass('public.xera_money_locks') IS NOT NULL THEN
        EXECUTE 'SELECT COALESCE(bool_or(locked), false) FROM xera_money_locks WHERE user_id = $1'
           INTO v_locked USING p_user_id;
        IF v_locked THEN RETURN 'account_locked'; END IF;
    END IF;

    IF EXISTS (SELECT 1 FROM xera_onchain_claims WHERE user_id = p_user_id AND status IN ('SIGNED', 'SUBMITTED')) THEN
        RETURN 'claim_in_progress';
    END IF;

    IF v_w.id IS NOT NULL AND xera_discount_spendable(p_user_id) < v_w.cached_balance THEN
        RETURN 'order_in_progress';
    END IF;

    IF EXISTS (SELECT 1 FROM xera_kyc WHERE user_id = p_user_id AND status = 'PENDING') THEN
        RETURN 'kyc_in_review';
    END IF;

    IF NOT COALESCE(p_skip_busy, false) AND xera_deletion_evosdata_busy(p_user_id) THEN
        RETURN 'evosdata_in_progress';
    END IF;
    RETURN NULL;
END;
$$;

-- One-argument version kept, so older callers (the status route) behave exactly as before.
CREATE OR REPLACE FUNCTION xera_deletion_blocker(p_user_id BIGINT) RETURNS TEXT
LANGUAGE sql
STABLE
SET search_path = public
AS $$
    SELECT xera_deletion_blocker_v3(p_user_id, false);
$$;

CREATE OR REPLACE FUNCTION xera_request_account_deletion_v3(p_user_id BIGINT, p_skip_busy BOOLEAN DEFAULT false) RETURNS xera_account_deletions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_cfg     xera_account_deletion_config;
    v_row     xera_account_deletions;
    v_blocker TEXT;
BEGIN
    SELECT * INTO v_cfg FROM xera_account_deletion_config WHERE id = 1;
    IF NOT COALESCE(v_cfg.enabled, false) THEN
        RAISE EXCEPTION 'deletion_disabled' USING ERRCODE = 'P0601';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM users WHERE id = p_user_id) THEN
        RAISE EXCEPTION 'user_not_found' USING ERRCODE = 'P0608';
    END IF;

    SELECT * INTO v_row FROM xera_account_deletions WHERE user_id = p_user_id AND status = 'PENDING';
    IF FOUND THEN RETURN v_row; END IF;

    PERFORM 1 FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;

    v_blocker := xera_deletion_blocker_v3(p_user_id, p_skip_busy);
    IF v_blocker IS NOT NULL THEN
        RAISE EXCEPTION '%', v_blocker USING ERRCODE = CASE v_blocker
            WHEN 'wallet_not_active' THEN 'P0602' WHEN 'account_locked' THEN 'P0603'
            WHEN 'claim_in_progress' THEN 'P0604' WHEN 'order_in_progress' THEN 'P0605'
            WHEN 'evosdata_in_progress' THEN 'P0609'
            ELSE 'P0606' END;
    END IF;

    INSERT INTO xera_account_deletions (user_id, purge_after, ignore_evosdata_busy)
    VALUES (p_user_id, now() + make_interval(days => v_cfg.grace_days), COALESCE(p_skip_busy, false))
    RETURNING * INTO v_row;
    RETURN v_row;
END;
$$;

CREATE OR REPLACE FUNCTION xera_complete_account_deletion(p_user_id BIGINT) RETURNS xera_account_deletions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_del   xera_account_deletions;
    v_w     xera_wallets;
    v_bal   NUMERIC(20,4) := 0;
    v_cust  NUMERIC(14,2) := 0;
    v_agent NUMERIC(14,2) := 0;
BEGIN
    SELECT * INTO v_del FROM xera_account_deletions
     WHERE user_id = p_user_id AND status = 'PENDING' FOR UPDATE;
    IF NOT FOUND OR v_del.purge_after > now() THEN
        RETURN NULL;
    END IF;

    SELECT * INTO v_w FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;
    IF xera_deletion_blocker_v3(p_user_id, COALESCE(v_del.ignore_evosdata_busy, false)) IS NOT NULL THEN
        RETURN NULL;
    END IF;

    -- ---- XERA (unchanged) ----
    IF v_w.id IS NOT NULL THEN
        v_bal := v_w.cached_balance;
        IF v_bal > 0 THEN
            INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id, metadata)
            VALUES (v_w.id, p_user_id, 'ACCOUNT_DELETION', v_bal, 'DEBIT', 'deletion:' || v_del.id,
                    jsonb_build_object('deletion_id', v_del.id));
        END IF;
        UPDATE xera_wallets SET cached_balance = 0, status = 'SUSPENDED', updated_at = now() WHERE id = v_w.id;
    END IF;

    UPDATE users SET
        username      = 'deleted_' || id,
        email         = 'deleted_' || id || '@deleted.invalid',
        full_name     = 'Deleted user',
        phone         = '',
        password      = '!deleted',
        referral_code = NULL
     WHERE id = p_user_id;
    BEGIN
        EXECUTE 'UPDATE users SET store_name = NULL WHERE id = $1' USING p_user_id;
    EXCEPTION WHEN undefined_column THEN NULL;
    END;

    UPDATE xera_kyc SET legal_name = NULL, country = NULL, id_type = NULL, id_last4 = NULL
     WHERE user_id = p_user_id;
    IF to_regclass('public.xera_notifications') IS NOT NULL THEN
        EXECUTE 'DELETE FROM xera_notifications WHERE user_id = $1' USING p_user_id;
    END IF;
    IF to_regclass('public.xera_name_changes') IS NOT NULL THEN
        EXECUTE 'UPDATE xera_name_changes SET old_name = NULL, new_name = ''(deleted)'' WHERE user_id = $1' USING p_user_id;
    END IF;

    -- ---- EVOS Data: customer wallet (GHS) ----
    IF to_regclass('public.customer_wallets') IS NOT NULL THEN
        EXECUTE 'SELECT COALESCE(balance, 0) FROM customer_wallets WHERE user_id = $1 FOR UPDATE'
           INTO v_cust USING p_user_id;
        v_cust := COALESCE(v_cust, 0);
        IF v_cust > 0 THEN
            IF to_regclass('public.customer_wallet_transactions') IS NOT NULL THEN
                EXECUTE 'INSERT INTO customer_wallet_transactions (user_id, type, amount, reference, note)
                         VALUES ($1, ''debit'', $2, $3, ''Account deleted: balance forfeited'')
                         ON CONFLICT DO NOTHING'
                   USING p_user_id, v_cust, 'deletion:' || v_del.id;
            END IF;
            EXECUTE 'UPDATE customer_wallets SET balance = 0, updated_at = now() WHERE user_id = $1' USING p_user_id;
        END IF;
    END IF;

    -- ---- EVOS Data: agent wallet (GHS). The ledger row is best effort: an unexpected ledger
    -- layout must never stop the deletion, so a failure there is skipped (the balance is still zeroed).
    IF to_regclass('public.agent_wallets') IS NOT NULL THEN
        EXECUTE 'SELECT COALESCE(balance, 0) FROM agent_wallets WHERE agent_id = $1 FOR UPDATE'
           INTO v_agent USING p_user_id;
        v_agent := COALESCE(v_agent, 0);
        IF v_agent > 0 THEN
            IF to_regclass('public.agent_transactions') IS NOT NULL THEN
                BEGIN
                    EXECUTE 'INSERT INTO agent_transactions (agent_id, amount, type, reference) VALUES ($1, $2, ''deletion'', $3)'
                       USING p_user_id, -v_agent, 'deletion:' || v_del.id;
                EXCEPTION WHEN OTHERS THEN NULL;
                END;
            END IF;
            EXECUTE 'UPDATE agent_wallets SET balance = 0 WHERE agent_id = $1' USING p_user_id;
        END IF;
    END IF;

    -- ---- EVOS Data personal data (orders and transactions are kept for accounting) ----
    IF to_regclass('public.password_resets') IS NOT NULL THEN
        EXECUTE 'DELETE FROM password_resets WHERE user_id = $1' USING p_user_id;
    END IF;
    IF to_regclass('public.afa_registrations') IS NOT NULL THEN
        EXECUTE 'UPDATE afa_registrations SET full_name = ''(deleted)'', phone_number = '''', id_number = ''(deleted)'',
                        occupation = NULL, location = NULL, region = NULL, date_of_birth = NULL, guest_email = NULL
                  WHERE user_id = $1' USING p_user_id;
    END IF;

    -- ---- EVOSGPT private data (shared knowledge has no user id and is never touched) ----
    IF to_regclass('public.evosgpt_memory') IS NOT NULL THEN
        EXECUTE 'DELETE FROM evosgpt_memory WHERE user_id = $1' USING p_user_id;
    END IF;
    IF to_regclass('public.evosgpt_long_memory') IS NOT NULL THEN
        EXECUTE 'DELETE FROM evosgpt_long_memory WHERE user_id = $1' USING p_user_id;
    END IF;
    IF to_regclass('public.evosgpt_daily_chats') IS NOT NULL THEN
        EXECUTE 'DELETE FROM evosgpt_daily_chats WHERE user_id = $1' USING p_user_id;
    END IF;
    IF to_regclass('public.evosgpt_usage_events') IS NOT NULL THEN
        EXECUTE 'DELETE FROM evosgpt_usage_events WHERE user_id = $1' USING p_user_id;
    END IF;

    UPDATE xera_account_deletions
       SET status = 'COMPLETED', completed_at = now(), forfeited_balance = v_bal, forfeited_ghs = v_cust + v_agent
     WHERE id = v_del.id
    RETURNING * INTO v_del;
    RETURN v_del;
END;
$$;

REVOKE ALL ON FUNCTION xera_deletion_blocker_v3(BIGINT, BOOLEAN), xera_deletion_blocker(BIGINT),
    xera_request_account_deletion_v3(BIGINT, BOOLEAN), xera_complete_account_deletion(BIGINT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION xera_deletion_blocker_v3(BIGINT, BOOLEAN), xera_deletion_blocker(BIGINT),
    xera_request_account_deletion_v3(BIGINT, BOOLEAN), xera_complete_account_deletion(BIGINT) TO service_role;

COMMIT;
