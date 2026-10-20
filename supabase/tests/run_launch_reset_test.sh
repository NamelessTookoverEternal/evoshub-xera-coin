#!/usr/bin/env bash
# Tests operations/xera_official_launch_reset.sql, _final_update.sql and _rollback.sql
# against DISPOSABLE databases. Exits non-zero on the first failure.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OPS="$HERE/../operations"
MIG="$HERE/../migrations"
BASE=xera_reset_test
FAILS=0
q() { psql -v ON_ERROR_STOP=1 -At -q -d "$1" -c "$2"; }
pass() { echo "  ok  - $1"; }
fail() { echo "  FAIL- $1"; FAILS=$((FAILS+1)); }
expect() { [ "$2" = "$3" ] && pass "$1" || fail "$1 (expected '$3', got '$2')"; }

confirmed_reset()    { sed "s/v_confirm TEXT := 'NO';/v_confirm TEXT := 'YES-RESET-XERA-TEST-DATA';/" "$OPS/xera_official_launch_reset.sql"; }
confirmed_rollback() { sed "s/v_confirm TEXT := 'NO';/v_confirm TEXT := 'YES-ROLLBACK-XERA-RESET';/" "$OPS/xera_official_launch_rollback.sql"; }

build() {   # build DB with migrations + realistic test-phase data
  local db=$1
  "$HERE/setup_xera_test_db.sh" "$db" >/dev/null 2>&1
  psql -v ON_ERROR_STOP=1 -q -d "$db" -f "$MIG/20261020_xera_official_mining_rewards.sql" >/dev/null
  psql -v ON_ERROR_STOP=1 -q -d "$db" -f "$MIG/20261021_xera_official_launch_v1.sql" >/dev/null 2>&1
  psql -v ON_ERROR_STOP=1 -q -d "$db" >/dev/null <<'SQL'
INSERT INTO users (id, username) SELECT g, 'u'||g FROM generate_series(1,5) g;
-- users 1,2: mined and claimed; user 3: active session; all three claimed daily
DO $$
DECLARE u INT; v TEXT; sid BIGINT;
BEGIN
  SELECT agreement_version INTO v FROM xera_launch_config;
  FOR u IN 1..3 LOOP
    PERFORM xera_accept_miner_agreement(u, v, repeat('a',64));
    PERFORM xera_start_mining_launch(u, 24, 5000);
    PERFORM xera_claim_daily_reward(u, 2);
  END LOOP;
  FOR u IN 1..2 LOOP
    UPDATE xera_mining_sessions SET expires_at = now() - interval '1 hour' WHERE user_id = u;
    SELECT id INTO sid FROM xera_mining_sessions WHERE user_id = u;
    PERFORM xera_claim_mining_reward(sid, u);
  END LOOP;
  -- a paid hashrate session for user 4 that already paid out 30 of 150
  INSERT INTO xera_wallets (user_id, cached_balance) VALUES (4, 30);
  INSERT INTO xera_hashrate_sessions (user_id, tier_id, payment_method, payment_currency, amount_paid, daily_rate, duration_days,
        maximum_entitlement, reserved_entitlement, rewarded_amount, started_at, expires_at, status)
  VALUES (4, 1, 'PAYSTACK', 'GHS', 1, 5, 30, 150, 150, 30, now(), now() + interval '20 days', 'ACTIVE');
  INSERT INTO xera_hashrate_payments (session_id, user_id, provider, reference, amount, currency, status)
  VALUES (1, 4, 'PAYSTACK', 'XERA-TEST-REF-1', 1, 'GHS', 'CONFIRMED');
  INSERT INTO xera_transactions (wallet_id, user_id, type, amount, direction, reference_id)
  SELECT id, 4, 'MINING_REWARD', 30, 'CREDIT', 'hashrate:1:30.0000' FROM xera_wallets WHERE user_id = 4;
  UPDATE xera_allocations SET mining_distributed = mining_distributed + 30 WHERE id = 1;
  UPDATE xera_mining_entitlement_state SET reserved_amount = reserved_amount + 150 WHERE id = 1;
  INSERT INTO xera_referrals (referrer_user_id, referred_user_id, status) VALUES (1, 5, 'pending');
END $$;
SQL
}

echo "== A. reset refuses without confirmation, changes nothing"
build ${BASE}_a
TX0=$(q ${BASE}_a "SELECT COUNT(*) FROM xera_transactions")
psql -v ON_ERROR_STOP=1 -q -d ${BASE}_a -f "$OPS/xera_official_launch_reset.sql" >/dev/null 2>&1
expect "unconfirmed run exits non-zero" "$?" "3"
expect "transactions untouched" "$(q ${BASE}_a "SELECT COUNT(*) FROM xera_transactions")" "$TX0"
expect "no backup schema created" "$(q ${BASE}_a "SELECT to_regnamespace('xera_backup_launch_reset') IS NULL")" "t"

echo "== B. confirmed reset"
PRE_BAL=$(q ${BASE}_a "SELECT SUM(cached_balance) FROM xera_wallets")
PRE_USERS=$(q ${BASE}_a "SELECT COUNT(*) FROM users")
PRE_WALLETS=$(q ${BASE}_a "SELECT COUNT(*) FROM xera_wallets")
PRE_SESS=$(q ${BASE}_a "SELECT COUNT(*) FROM xera_mining_sessions")
PRE_DIST=$(q ${BASE}_a "SELECT mining_distributed FROM xera_allocations WHERE id=1")
PRE_RES=$(q ${BASE}_a "SELECT reserved_amount FROM xera_mining_entitlement_state WHERE id=1")
confirmed_reset | psql -v ON_ERROR_STOP=1 -q -d ${BASE}_a >/tmp/reset_out.txt 2>&1
expect "reset succeeds" "$?" "0"
expect "no transactions" "$(q ${BASE}_a "SELECT COUNT(*) FROM xera_transactions")" "0"
expect "no sessions" "$(q ${BASE}_a "SELECT COUNT(*) FROM xera_mining_sessions")" "0"
expect "all cached balances zero" "$(q ${BASE}_a "SELECT SUM(cached_balance) FROM xera_wallets")" "0.0000"
expect "wallet rows preserved" "$(q ${BASE}_a "SELECT COUNT(*) FROM xera_wallets")" "$PRE_WALLETS"
expect "users preserved" "$(q ${BASE}_a "SELECT COUNT(*) FROM users")" "$PRE_USERS"
expect "daily-claim rows kept, progress cleared" "$(q ${BASE}_a "SELECT COUNT(*) FILTER (WHERE last_claim_date IS NULL AND streak=0 AND total_claims=0) || '/' || COUNT(*) FROM xera_daily_claims")" "3/3"
expect "mining_distributed reset" "$(q ${BASE}_a "SELECT mining_distributed FROM xera_allocations WHERE id=1")" "0.0000"
expect "supply + allocation unchanged" "$(q ${BASE}_a "SELECT total_target||'/'||mining_allocation FROM xera_allocations WHERE id=1")" "500000000.0000/75000000.0000"
expect "entitlement ledger re-based to paid hashrate remainder (150-30)" "$(q ${BASE}_a "SELECT reserved_amount FROM xera_mining_entitlement_state WHERE id=1")" "120.0000"
expect "hashrate session + payment preserved" "$(q ${BASE}_a "SELECT (SELECT COUNT(*) FROM xera_hashrate_sessions)||'/'||(SELECT COUNT(*) FROM xera_hashrate_payments)")" "1/1"
expect "referral link preserved" "$(q ${BASE}_a "SELECT COUNT(*) FROM xera_referrals")" "1"
expect "backup: transactions" "$(q ${BASE}_a "SELECT COUNT(*) FROM xera_backup_launch_reset.xera_transactions")" "$TX0"
expect "backup: sessions" "$(q ${BASE}_a "SELECT COUNT(*) FROM xera_backup_launch_reset.xera_mining_sessions")" "$PRE_SESS"
expect "backup: balances" "$(q ${BASE}_a "SELECT SUM(cached_balance) FROM xera_backup_launch_reset.xera_wallets")" "$PRE_BAL"
expect "backup: distributed counter" "$(q ${BASE}_a "SELECT mining_distributed FROM xera_backup_launch_reset.xera_allocations")" "$PRE_DIST"
expect "backup: entitlement counter" "$(q ${BASE}_a "SELECT reserved_amount FROM xera_backup_launch_reset.xera_mining_entitlement_state")" "$PRE_RES"
expect "backups not readable by anon" "$(q ${BASE}_a "SELECT has_table_privilege('anon','xera_backup_launch_reset.xera_wallets','SELECT') OR has_schema_privilege('anon','xera_backup_launch_reset','USAGE')")" "f"
expect "backups not readable by authenticated" "$(q ${BASE}_a "SELECT has_table_privilege('authenticated','xera_backup_launch_reset.xera_transactions','SELECT') OR has_schema_privilege('authenticated','xera_backup_launch_reset','USAGE')")" "f"
expect "backup tables have RLS enabled" "$(q ${BASE}_a "SELECT bool_and(c.relrowsecurity) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='xera_backup_launch_reset' AND c.relkind='r'")" "t"
expect "ledger reconciles" "$(q ${BASE}_a "SELECT xera_launch_reconcile()->>'ok'")" "true"

echo "== C. second run is refused"
confirmed_reset | psql -v ON_ERROR_STOP=1 -q -d ${BASE}_a >/dev/null 2>&1
expect "re-running the reset fails" "$?" "3"
expect "backups still present" "$(q ${BASE}_a "SELECT COUNT(*) FROM xera_backup_launch_reset.xera_transactions")" "$TX0"

echo "== D. final-update + launch flow on the reset database"
psql -v ON_ERROR_STOP=1 -q -d ${BASE}_a -f "$OPS/xera_official_launch_final_update.sql" >/dev/null 2>&1
expect "final update succeeds" "$?" "0"
psql -v ON_ERROR_STOP=1 -q -d ${BASE}_a -f "$OPS/xera_official_launch_final_update.sql" >/dev/null 2>&1
expect "final update is idempotent" "$?" "0"
expect "daily reward = 2" "$(q ${BASE}_a "SELECT reward_amount FROM xera_daily_config WHERE id=1")" "2.0000"
expect "bonus enabled 100 x 100 <= 10000" "$(q ${BASE}_a "SELECT bonus_enabled||'/'||bonus_max_recipients||'/'||bonus_amount||'/'||bonus_pool_cap FROM xera_launch_config")" "true/100/100.0000/10000.0000"
expect "existing wallets did NOT receive a bonus" "$(q ${BASE}_a "SELECT COUNT(*) FROM xera_early_miner_bonuses")" "0"
expect "existing wallets still zero" "$(q ${BASE}_a "SELECT SUM(cached_balance) FROM xera_wallets")" "0.0000"
# a miner after launch gets exactly one bonus, accounting stays consistent
q ${BASE}_a "SELECT xera_accept_miner_agreement(1,(SELECT agreement_version FROM xera_launch_config),repeat('d',64))" >/dev/null
OUT=$(q ${BASE}_a "SELECT xera_start_mining_launch(1,24,5000)->>'bonus_status'")
expect "first post-reset miner gets the bonus" "$OUT" "GRANTED"
expect "post-launch reconcile ok" "$(q ${BASE}_a "SELECT xera_launch_reconcile()->>'ok'")" "true"
expect "pool = bonus (100) + 0 rewards; entitlement = 100 + 120 hashrate" "$(q ${BASE}_a "SELECT (SELECT mining_distributed FROM xera_allocations)||'/'||(SELECT reserved_amount FROM xera_mining_entitlement_state)")" "100.0000/220.0000"

echo "== E. rollback is refused once launch activity exists, allowed before"
confirmed_rollback | psql -v ON_ERROR_STOP=1 -q -d ${BASE}_a >/dev/null 2>&1
expect "rollback refused after launch activity" "$?" "3"
expect "launch data untouched by refused rollback" "$(q ${BASE}_a "SELECT COUNT(*) FROM xera_early_miner_bonuses")" "1"

build ${BASE}_r
R_TX=$(q ${BASE}_r "SELECT COUNT(*) FROM xera_transactions"); R_BAL=$(q ${BASE}_r "SELECT SUM(cached_balance) FROM xera_wallets")
R_DIST=$(q ${BASE}_r "SELECT mining_distributed FROM xera_allocations WHERE id=1"); R_RES=$(q ${BASE}_r "SELECT reserved_amount FROM xera_mining_entitlement_state WHERE id=1")
confirmed_reset | psql -v ON_ERROR_STOP=1 -q -d ${BASE}_r >/dev/null 2>&1
psql -v ON_ERROR_STOP=1 -q -d ${BASE}_r -f "$OPS/xera_official_launch_rollback.sql" >/dev/null 2>&1
expect "unconfirmed rollback refused" "$?" "3"
confirmed_rollback | psql -v ON_ERROR_STOP=1 -q -d ${BASE}_r >/dev/null 2>&1
expect "confirmed rollback succeeds" "$?" "0"
expect "rollback restored transactions" "$(q ${BASE}_r "SELECT COUNT(*) FROM xera_transactions")" "$R_TX"
expect "rollback restored balances" "$(q ${BASE}_r "SELECT SUM(cached_balance) FROM xera_wallets")" "$R_BAL"
expect "rollback restored counters" "$(q ${BASE}_r "SELECT (SELECT mining_distributed FROM xera_allocations)||'/'||(SELECT reserved_amount FROM xera_mining_entitlement_state)")" "$R_DIST/$R_RES"
expect "backups kept after rollback" "$(q ${BASE}_r "SELECT to_regclass('xera_backup_launch_reset.xera_transactions') IS NOT NULL")" "t"

echo "== F. preconditions abort and leave the database untouched"
precond() {   # name, setup SQL
  local db=${BASE}_p; build $db
  psql -v ON_ERROR_STOP=1 -q -d $db -c "$2" >/dev/null 2>&1
  local before; before=$(q $db "SELECT COUNT(*) FROM xera_transactions")
  confirmed_reset | psql -v ON_ERROR_STOP=1 -q -d $db >/dev/null 2>&1
  expect "$1: reset aborts" "$?" "3"
  expect "$1: nothing deleted" "$(q $db "SELECT COUNT(*) FROM xera_transactions")" "$before"
  expect "$1: no backup schema left behind" "$(q $db "SELECT to_regnamespace('xera_backup_launch_reset') IS NULL")" "t"
}
precond "existing on-chain claim"   "INSERT INTO xera_onchain_claims (reference_id,user_id,chain,wallet_address,claimed_amount,transferable_amount,locked_amount,signature_deadline) VALUES ('t-1',1,'BNB','0xabc',4,1,3,now())"
precond "launch bonus already paid" "UPDATE xera_launch_state SET bonus_slots_used = 1, bonus_distributed = 100"
precond "missing launch function"   "DROP FUNCTION xera_launch_reconcile()"
precond "altered mining allocation" "UPDATE xera_allocations SET mining_allocation = 70000000 WHERE id = 1"
precond "missing required index"    "DROP INDEX xera_one_active_session_per_user"
precond "singleton row missing"     "DELETE FROM xera_launch_config"

echo "== G. final update refuses to run before the reset"
build ${BASE}_g
psql -v ON_ERROR_STOP=1 -q -d ${BASE}_g -f "$OPS/xera_official_launch_final_update.sql" >/dev/null 2>&1
expect "final update aborts when reset not run" "$?" "3"
expect "bonus stays disabled" "$(q ${BASE}_g "SELECT bonus_enabled FROM xera_launch_config")" "f"

echo "== H. superseded script cannot be run"
psql -v ON_ERROR_STOP=1 -q -d ${BASE}_g -f "$OPS/xera_official_test_reset.sql" >/dev/null 2>&1
expect "old reset script fails by design" "$?" "3"

for s in a r p g; do dropdb --if-exists ${BASE}_$s >/dev/null 2>&1; done
echo; [ $FAILS -eq 0 ] && echo "ALL RESET/FINAL-UPDATE/ROLLBACK TESTS PASSED" || { echo "$FAILS FAILURE(S)"; exit 1; }
