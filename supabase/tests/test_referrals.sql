-- Referral SQL tests. Run against a disposable DB that already has the V1,
-- daily-claim and referrals migrations applied (see README.md in this folder).
-- Everything runs in one transaction and is rolled back: it leaves no data behind.
--
--   psql -d xera_test -v ON_ERROR_STOP=1 -f test_referrals.sql
--
-- Needs `users` to have the shared columns (referral_code, referred_by).

BEGIN;

DO $$
DECLARE
    a BIGINT; k BIGINT; y BIGINT; z BIGINT;
    r RECORD;
BEGIN
    INSERT INTO users (username, referral_code) VALUES ('t_ama',  'EVOS-TAMA-ABCD') RETURNING id INTO a;   -- EVOSGPT format
    INSERT INTO users (username, referral_code) VALUES ('t_kofi', 't_kofi_1234')    RETURNING id INTO k;   -- EVOS Data format
    INSERT INTO users (username)                VALUES ('t_yaw')                    RETURNING id INTO y;   -- no code yet
    INSERT INTO users (username, referral_code, referred_by) VALUES ('t_zed', 'EVOS-TZED-0001', 'EVOS-TAMA-ABCD') RETURNING id INTO z;

    -- resolve: exact + case-insensitive, "_" is not a wildcard
    ASSERT (SELECT id FROM xera_resolve_referral_code('T_KOFI_1234')) = k, 'resolve should be case-insensitive';
    ASSERT NOT EXISTS (SELECT 1 FROM xera_resolve_referral_code('t_kofiX1234')), 'underscore must not act as a wildcard';

    -- signup link: sets users.referred_by to the canonical code, records the row
    ASSERT xera_link_referral(y, 'T_KOFI_1234', 'xera') = k, 'link should return the referrer';
    ASSERT (SELECT referred_by FROM users WHERE id = y) = 't_kofi_1234', 'referred_by should be canonical';

    -- first touch wins
    ASSERT xera_link_referral(y, 'EVOS-TAMA-ABCD', 'xera') = k, 'second code must be ignored';
    ASSERT (SELECT count(*) FROM xera_referrals WHERE referred_user_id = y) = 1, 'one referrer per user';

    -- self / unknown / nothing to link
    ASSERT xera_link_referral(k, 't_kofi_1234') IS NULL, 'self-referral must be rejected';
    ASSERT xera_link_referral(a, 'NOPE-0000')   IS NULL, 'unknown code must be rejected';
    ASSERT xera_link_referral(k, NULL)          IS NULL, 'no code and no referred_by -> nothing';

    -- cross-product sync (referred inside EVOSGPT/EVOS Data, first opens XERA later)
    ASSERT NOT EXISTS (SELECT 1 FROM xera_referrals WHERE referred_user_id = z);
    ASSERT xera_link_referral(z, NULL, 'ecosystem') = a, 'sync from users.referred_by';
    ASSERT (SELECT source_product FROM xera_referrals WHERE referred_user_id = z) = 'ecosystem';

    -- qualify with rewards off: qualifies, pays nothing
    UPDATE xera_config SET referral_enabled = false WHERE id = 1;
    SELECT * INTO r FROM xera_qualify_referral(y);
    ASSERT r.qualified AND r.referrer_paid = 0 AND r.referee_paid = 0, 'qualify with rewards off';
    SELECT * INTO r FROM xera_qualify_referral(y);
    ASSERT NOT r.qualified, 'qualify must be idempotent';
    ASSERT (SELECT count(*) FROM xera_transactions WHERE type = 'REFERRAL_REWARD') = 0, 'no ledger rows when off';

    -- rewards on: both sides paid exactly once
    UPDATE xera_config SET referral_enabled = true WHERE id = 1;
    UPDATE xera_referral_config SET referrer_reward = 50, referee_reward = 20 WHERE id = 1;
    SELECT * INTO r FROM xera_qualify_referral(z);
    ASSERT r.referrer_paid = 50 AND r.referee_paid = 20, 'both sides paid';
    ASSERT (SELECT cached_balance FROM xera_wallets WHERE user_id = a) = 50;
    ASSERT (SELECT cached_balance FROM xera_wallets WHERE user_id = z) = 20;
    SELECT * INTO r FROM xera_qualify_referral(z);
    ASSERT r.referrer_paid = 0 AND r.referee_paid = 0, 'replay pays nothing';
    ASSERT (SELECT count(*) FROM xera_transactions WHERE type = 'REFERRAL_REWARD') = 2, 'exactly two ledger rows';
    ASSERT (SELECT cached_balance FROM xera_wallets WHERE user_id = a)
         = (SELECT sum(amount) FROM xera_transactions WHERE user_id = a), 'balance matches ledger';

    -- suspended referrer wallet: not paid, referee still is
    INSERT INTO xera_wallets (user_id, status) VALUES (k, 'SUSPENDED');
    UPDATE xera_referrals SET qualified_at = NULL, status = 'pending' WHERE referred_user_id = y;
    SELECT * INTO r FROM xera_qualify_referral(y);
    ASSERT r.referrer_paid = 0 AND r.referee_paid = 20, 'suspended referrer must not be paid';

    RAISE NOTICE 'ALL REFERRAL TESTS PASSED';
END $$;

ROLLBACK;
