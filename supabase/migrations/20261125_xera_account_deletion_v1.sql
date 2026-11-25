-- ============================================================
-- XERA: users can delete their own account (7-day grace period)
-- ============================================================
-- HOW IT WORKS
--   1. The user asks to delete (the backend checks their password first). The request is
--      recorded as PENDING with purge_after = now + grace_days (default 7). Nothing else changes:
--      the account keeps working and the user can cancel any time before the date.
--   2. When the date passes, xera_complete_account_deletion() ANONYMISES the account:
--        * users: username/email/name/phone/password/invite code are replaced, so nobody can sign in again
--        * the remaining in-app Pure XERA balance is forfeited (one ledger row, ACCOUNT_DELETION) and the
--          wallet is closed (SUSPENDED: no mining, no sends)
--        * KYC details (legal name, country, ID type, last 4) are erased; the backend also erases ID photos
--        * notifications are deleted; names in the name-change history are blanked
--      The user ROW, the wallet row, ledger rows, transfers and the public ledger stay (they carry no
--      personal data once anonymised) so balances and totals still add up and nothing breaks.
--   3. Anything already claimed on-chain stays in the user's own wallet. Deletion never touches it.
--
-- BLOCKED while any of these is true (the user is told why):
--   wallet not ACTIVE (suspended / flagged) | money lock | on-chain claim in progress
--   | a data order is holding XERA | identity check under review
--   (checked again on the purge date: if one appears later, the purge waits)
--
-- WHAT THIS DOES NOT TOUCH: on-chain claim/withdraw code, mining, P2P, KYC decisions, allocations.
-- Additive, re-runnable. Run in Supabase SQL Editor (production).
-- Error codes: P0601 deletion_disabled, P0602 wallet_not_active, P0603 account_locked,
--   P0604 claim_in_progress, P0605 order_in_progress, P0606 kyc_in_review,
--   P0607 no_pending_deletion, P0608 user_not_found.
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS xera_account_deletion_config (
    id         SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled    BOOLEAN NOT NULL DEFAULT true,
    grace_days INTEGER NOT NULL DEFAULT 7 CHECK (grace_days BETWEEN 0 AND 90)
);
INSERT INTO xera_account_deletion_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS xera_account_deletions (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            BIGINT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'CANCELLED', 'COMPLETED')),
    requested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    purge_after        TIMESTAMPTZ NOT NULL,
    cancelled_at       TIMESTAMPTZ,
    completed_at       TIMESTAMPTZ,
    forfeited_balance  NUMERIC(20,4) NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS xera_account_deletions_one_pending
    ON xera_account_deletions (user_id) WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS xera_account_deletions_due
    ON xera_account_deletions (purge_after) WHERE status = 'PENDING';

-- ledger type for the forfeited balance (keeps every existing type)
ALTER TABLE xera_transactions DROP CONSTRAINT IF EXISTS xera_transactions_type_check;
ALTER TABLE xera_transactions ADD CONSTRAINT xera_transactions_type_check CHECK (type IN (
    'MINING_REWARD','XERA_PURCHASE','REFERRAL_REWARD','BONUS','DAILY_CLAIM',
    'ADMIN_CREDIT','ADMIN_DEBIT','REVERSAL','MIGRATION','ONCHAIN_CLAIM','DISCOUNT_SPEND',
    'P2P_SEND','P2P_RECEIVE','P2P_FEE','NAME_CHANGE_FEE','ACCOUNT_DELETION'
));
CREATE UNIQUE INDEX IF NOT EXISTS xera_tx_account_deletion_unique
    ON xera_transactions (reference_id) WHERE type = 'ACCOUNT_DELETION';

-- Why can't this account be deleted right now? NULL = it can.
CREATE OR REPLACE FUNCTION xera_deletion_blocker(p_user_id BIGINT) RETURNS TEXT
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

    -- Tokens held for a pending data order: spendable is lower than the balance.
    IF v_w.id IS NOT NULL AND xera_discount_spendable(p_user_id) < v_w.cached_balance THEN
        RETURN 'order_in_progress';
    END IF;

    IF EXISTS (SELECT 1 FROM xera_kyc WHERE user_id = p_user_id AND status = 'PENDING') THEN
        RETURN 'kyc_in_review';
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION xera_request_account_deletion(p_user_id BIGINT) RETURNS xera_account_deletions
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

    -- Already scheduled: return it (double tap / retry).
    SELECT * INTO v_row FROM xera_account_deletions WHERE user_id = p_user_id AND status = 'PENDING';
    IF FOUND THEN RETURN v_row; END IF;

    -- Serialise with other wallet operations of this user.
    PERFORM 1 FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;

    v_blocker := xera_deletion_blocker(p_user_id);
    IF v_blocker IS NOT NULL THEN
        RAISE EXCEPTION '%', v_blocker USING ERRCODE = CASE v_blocker
            WHEN 'wallet_not_active' THEN 'P0602' WHEN 'account_locked' THEN 'P0603'
            WHEN 'claim_in_progress' THEN 'P0604' WHEN 'order_in_progress' THEN 'P0605'
            ELSE 'P0606' END;
    END IF;

    INSERT INTO xera_account_deletions (user_id, purge_after)
    VALUES (p_user_id, now() + make_interval(days => v_cfg.grace_days))
    RETURNING * INTO v_row;
    RETURN v_row;
END;
$$;

CREATE OR REPLACE FUNCTION xera_cancel_account_deletion(p_user_id BIGINT) RETURNS xera_account_deletions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row xera_account_deletions;
BEGIN
    UPDATE xera_account_deletions SET status = 'CANCELLED', cancelled_at = now()
     WHERE user_id = p_user_id AND status = 'PENDING' AND completed_at IS NULL
    RETURNING * INTO v_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no_pending_deletion' USING ERRCODE = 'P0607';
    END IF;
    RETURN v_row;
END;
$$;

-- Ids whose date has passed.
CREATE OR REPLACE FUNCTION xera_due_account_deletions() RETURNS SETOF BIGINT
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT user_id FROM xera_account_deletions
     WHERE status = 'PENDING' AND purge_after <= now()
     ORDER BY purge_after LIMIT 50;
$$;

-- Anonymise one account whose date has passed. Returns the finished row, or NULL when it was not
-- done (not due yet / cancelled / a blocker appeared: it stays PENDING and is tried again later).
CREATE OR REPLACE FUNCTION xera_complete_account_deletion(p_user_id BIGINT) RETURNS xera_account_deletions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_del xera_account_deletions;
    v_w   xera_wallets;
    v_bal NUMERIC(20,4) := 0;
BEGIN
    SELECT * INTO v_del FROM xera_account_deletions
     WHERE user_id = p_user_id AND status = 'PENDING' FOR UPDATE;
    IF NOT FOUND OR v_del.purge_after > now() THEN
        RETURN NULL;
    END IF;

    SELECT * INTO v_w FROM xera_wallets WHERE user_id = p_user_id FOR UPDATE;
    IF xera_deletion_blocker(p_user_id) IS NOT NULL THEN
        RETURN NULL;
    END IF;

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

    UPDATE xera_kyc SET legal_name = NULL, country = NULL, id_type = NULL, id_last4 = NULL
     WHERE user_id = p_user_id;
    IF to_regclass('public.xera_notifications') IS NOT NULL THEN
        EXECUTE 'DELETE FROM xera_notifications WHERE user_id = $1' USING p_user_id;
    END IF;
    IF to_regclass('public.xera_name_changes') IS NOT NULL THEN
        EXECUTE 'UPDATE xera_name_changes SET old_name = NULL, new_name = ''(deleted)'' WHERE user_id = $1' USING p_user_id;
    END IF;

    UPDATE xera_account_deletions
       SET status = 'COMPLETED', completed_at = now(), forfeited_balance = v_bal
     WHERE id = v_del.id
    RETURNING * INTO v_del;
    RETURN v_del;
END;
$$;

-- LOCK-DOWN: service_role (backend) only
ALTER TABLE xera_account_deletion_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_account_deletions       ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON xera_account_deletion_config, xera_account_deletions FROM PUBLIC, anon, authenticated;
GRANT SELECT, UPDATE ON xera_account_deletion_config TO service_role;
GRANT SELECT ON xera_account_deletions TO service_role;
GRANT USAGE, SELECT ON SEQUENCE xera_account_deletions_id_seq TO service_role;
REVOKE ALL ON FUNCTION xera_deletion_blocker(BIGINT), xera_request_account_deletion(BIGINT),
    xera_cancel_account_deletion(BIGINT), xera_due_account_deletions(),
    xera_complete_account_deletion(BIGINT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION xera_deletion_blocker(BIGINT), xera_request_account_deletion(BIGINT),
    xera_cancel_account_deletion(BIGINT), xera_due_account_deletions(),
    xera_complete_account_deletion(BIGINT) TO service_role;

COMMIT;

-- Settings:
--   UPDATE xera_account_deletion_config SET grace_days = 14 WHERE id = 1;
--   UPDATE xera_account_deletion_config SET enabled = false WHERE id = 1;   -- pause new requests
