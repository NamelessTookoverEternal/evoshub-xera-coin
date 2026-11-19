-- ============================================================
-- XERA P2P v4: automatic "money lock" for flagged wallets
-- ============================================================
-- Run AFTER 20261118_xera_p2p_verified_fee_v3.sql. Additive and re-runnable.
--
-- WHAT THIS DOES
--   1. Adds an on/off switch (xera_p2p_config.auto_lock_enabled, default OFF).
--   2. Adds xera_money_locks: one row per account whose MONEY side is locked.
--      A locked account can still sign in, see its balance, mine, receive
--      transfers and contact support. It cannot SEND (P2P transfer) or
--      WITHDRAW (on-chain claim). The backend enforces this.
--   3. xera_p2p_autolock_scan(): when the switch is on, locks BOTH sides of a
--      flag: the flagged receiving wallet, and the senders involved (senders
--      that had not finished verification, or that shared an IP with another
--      sender to that wallet). Every flag type triggers it.
--      An account an admin has unlocked is only locked again if NEW transfers
--      involving it arrive after the unlock.
--   4. xera_money_unlock(): admin unlock with a reason, and an optional
--      "false flag, reward user" credit through the normal admin-credit ledger.
--
-- DOES NOT TOUCH: xera_wallets.status (the old SUSPENDED state also blocks
-- mining, so it is NOT used), on-chain claim SQL, mining, referrals, KYC.
-- ============================================================

BEGIN;

-- 1. SWITCH ---------------------------------------------------
ALTER TABLE xera_p2p_config
    ADD COLUMN IF NOT EXISTS auto_lock_enabled BOOLEAN NOT NULL DEFAULT false;

-- 2. LOCK TABLE -----------------------------------------------
CREATE TABLE IF NOT EXISTS xera_money_locks (
    user_id          BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    locked           BOOLEAN       NOT NULL DEFAULT true,
    locked_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    lock_source      TEXT          NOT NULL DEFAULT 'auto' CHECK (lock_source IN ('auto','admin')),
    lock_role        TEXT          CHECK (lock_role IN ('receiver','sender')),
    lock_reasons     TEXT[]        NOT NULL DEFAULT '{}',
    related_xera_id  TEXT,                      -- the flagged wallet this lock came from
    lock_count       INTEGER       NOT NULL DEFAULT 1,
    unlocked_at      TIMESTAMPTZ,               -- also the "cleared" marker for re-lock logic
    unlocked_by      BIGINT,
    unlock_reason    TEXT,
    false_flag       BOOLEAN,
    reward_amount    NUMERIC(20,4)
);
CREATE INDEX IF NOT EXISTS idx_xera_money_locks_locked ON xera_money_locks (locked) WHERE locked;

ALTER TABLE xera_money_locks ENABLE ROW LEVEL SECURITY;   -- no policies: backend (service role) only
REVOKE ALL ON xera_money_locks FROM PUBLIC, anon, authenticated;

-- 3. SCAN -----------------------------------------------------
CREATE OR REPLACE FUNCTION xera_p2p_autolock_scan()
RETURNS TABLE (locked_user_id BIGINT, locked_role TEXT, related_xera_id TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_cfg  xera_p2p_config;
    f      RECORD;
    s      RECORD;
    v_new  BIGINT;
BEGIN
    SELECT * INTO v_cfg FROM xera_p2p_config WHERE id = 1;
    IF NOT COALESCE(v_cfg.auto_lock_enabled, false) THEN
        RETURN;
    END IF;

    FOR f IN SELECT * FROM xera_p2p_flagged() LOOP
        -- (a) the flagged receiving wallet
        IF EXISTS (
            SELECT 1 FROM xera_p2p_transfers t
             WHERE t.recipient_user_id = f.recipient_user_id
               AND t.created_at > COALESCE((SELECT l.unlocked_at FROM xera_money_locks l WHERE l.user_id = f.recipient_user_id), '-infinity'::timestamptz)
               AND t.created_at > now() - make_interval(days => v_cfg.flag_window_days)
        ) THEN
            v_new := NULL;
            INSERT INTO xera_money_locks AS l (user_id, lock_source, lock_role, lock_reasons, related_xera_id)
            VALUES (f.recipient_user_id, 'auto', 'receiver', f.reasons, f.recipient_xera_id)
            ON CONFLICT (user_id) DO UPDATE
               SET locked = true, locked_at = now(), lock_source = 'auto', lock_role = 'receiver',
                   lock_reasons = EXCLUDED.lock_reasons, related_xera_id = EXCLUDED.related_xera_id,
                   lock_count = l.lock_count + 1
             WHERE NOT l.locked
            RETURNING l.user_id INTO v_new;
            IF v_new IS NOT NULL THEN
                locked_user_id := v_new; locked_role := 'receiver'; related_xera_id := f.recipient_xera_id;
                RETURN NEXT;
            END IF;
        END IF;

        -- (b) the senders involved in this flag
        FOR s IN
            SELECT DISTINCT w.sender_user_id AS uid
              FROM xera_p2p_transfers w
             WHERE w.recipient_user_id = f.recipient_user_id
               AND w.created_at > now() - make_interval(days => v_cfg.flag_window_days)
               AND w.created_at > COALESCE((SELECT l.unlocked_at FROM xera_money_locks l WHERE l.user_id = w.sender_user_id), '-infinity'::timestamptz)
               AND (
                    w.sender_verified IS NOT TRUE
                    OR (w.ip_address IS NOT NULL AND EXISTS (
                          SELECT 1 FROM xera_p2p_transfers o
                           WHERE o.recipient_user_id = w.recipient_user_id
                             AND o.ip_address = w.ip_address
                             AND o.sender_user_id <> w.sender_user_id
                             AND o.created_at > now() - make_interval(days => v_cfg.flag_window_days)))
               )
        LOOP
            v_new := NULL;
            INSERT INTO xera_money_locks AS l (user_id, lock_source, lock_role, lock_reasons, related_xera_id)
            VALUES (s.uid, 'auto', 'sender', ARRAY['sent_to_flagged_wallet'], f.recipient_xera_id)
            ON CONFLICT (user_id) DO UPDATE
               SET locked = true, locked_at = now(), lock_source = 'auto', lock_role = 'sender',
                   lock_reasons = EXCLUDED.lock_reasons, related_xera_id = EXCLUDED.related_xera_id,
                   lock_count = l.lock_count + 1
             WHERE NOT l.locked
            RETURNING l.user_id INTO v_new;
            IF v_new IS NOT NULL THEN
                locked_user_id := v_new; locked_role := 'sender'; related_xera_id := f.recipient_xera_id;
                RETURN NEXT;
            END IF;
        END LOOP;
    END LOOP;
END;
$$;

-- 4. UNLOCK (+ optional false-flag reward, same transaction) ---
CREATE OR REPLACE FUNCTION xera_money_unlock(
    p_user_id    BIGINT,
    p_admin_id   BIGINT,
    p_reason     TEXT,
    p_false_flag BOOLEAN DEFAULT false,
    p_reward     NUMERIC DEFAULT 0
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row     xera_money_locks;
    v_balance NUMERIC;
BEGIN
    IF p_reason IS NULL OR length(btrim(p_reason)) < 3 THEN
        RAISE EXCEPTION 'reason_required' USING ERRCODE = 'P0011';
    END IF;
    IF COALESCE(p_reward, 0) < 0 OR (COALESCE(p_reward, 0) > 0 AND NOT COALESCE(p_false_flag, false)) THEN
        RAISE EXCEPTION 'invalid_reward' USING ERRCODE = 'P0012';
    END IF;

    SELECT * INTO v_row FROM xera_money_locks WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND OR NOT v_row.locked THEN
        RAISE EXCEPTION 'not_locked' USING ERRCODE = 'P0013';
    END IF;

    UPDATE xera_money_locks
       SET locked = false, unlocked_at = now(), unlocked_by = p_admin_id,
           unlock_reason = btrim(p_reason), false_flag = COALESCE(p_false_flag, false),
           reward_amount = NULLIF(p_reward, 0)
     WHERE user_id = p_user_id;

    IF COALESCE(p_reward, 0) > 0 THEN
        v_balance := xera_admin_adjust_balance(p_admin_id, p_user_id, p_reward, 'CREDIT',
                                               'False-flag reward after money lock: ' || btrim(p_reason));
    END IF;

    INSERT INTO xera_admin_actions (admin_id, action, old_value, new_value, reason)
    VALUES (p_admin_id, 'MONEY_UNLOCKED',
            jsonb_build_object('user_id', p_user_id, 'locked', true, 'reasons', to_jsonb(v_row.lock_reasons)),
            jsonb_build_object('user_id', p_user_id, 'locked', false, 'false_flag', COALESCE(p_false_flag, false), 'reward', COALESCE(p_reward, 0)),
            btrim(p_reason));

    RETURN jsonb_build_object('user_id', p_user_id, 'reward', COALESCE(p_reward, 0), 'new_balance', v_balance);
END;
$$;

-- 5. LOCK-DOWN (backend / service_role only) -------------------
REVOKE EXECUTE ON FUNCTION xera_p2p_autolock_scan() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION xera_money_unlock(BIGINT, BIGINT, TEXT, BOOLEAN, NUMERIC) FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION xera_p2p_autolock_scan() TO service_role;
GRANT  EXECUTE ON FUNCTION xera_money_unlock(BIGINT, BIGINT, TEXT, BOOLEAN, NUMERIC) TO service_role;

COMMIT;

-- Verify after running:
--   SELECT auto_lock_enabled FROM xera_p2p_config;        -- false (switch it on in the admin console when ready)
--   SELECT count(*) FROM xera_money_locks;                -- 0
