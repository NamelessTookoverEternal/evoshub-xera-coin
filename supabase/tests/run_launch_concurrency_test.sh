#!/usr/bin/env bash
# REAL parallel Postgres sessions (not mocks) against a disposable DB:
#   1. same user double-submits           -> exactly 1 session, <=1 bonus
#   2. 6 users race for the last 2 slots  -> exactly 2 bonuses, slots end at 100
#   3. 4 users race across the 100/101 tier boundary -> exactly one earns 10, three earn 8
#   4. same user claims the daily reward 6x in parallel -> exactly 1 credit of 2 XERA
# Usage: ./run_launch_concurrency_test.sh [dbname]
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DB="${1:-xera_launch_conc}"
FAILS=0
q() { psql -v ON_ERROR_STOP=1 -At -q -d "$DB" -c "$1"; }
expect() { [ "$2" = "$3" ] && echo "  ok  - $1" || { echo "  FAIL- $1 (expected '$3', got '$2')"; FAILS=$((FAILS+1)); }; }

"$HERE/setup_xera_test_db.sh" "$DB" >/dev/null 2>&1
psql -v ON_ERROR_STOP=1 -q -d "$DB" -f "$HERE/../migrations/20261020_xera_official_mining_rewards.sql" >/dev/null
psql -v ON_ERROR_STOP=1 -q -d "$DB" -f "$HERE/../migrations/20261021_xera_official_launch_v1.sql" >/dev/null 2>&1
q "UPDATE xera_launch_config SET bonus_enabled = true" >/dev/null
q "INSERT INTO users (id, username) SELECT g, 'u'||g FROM generate_series(1,2000) g" >/dev/null
q "DO \$\$ DECLARE g INT; v TEXT; BEGIN SELECT agreement_version INTO v FROM xera_launch_config;
   FOR g IN 1..2000 LOOP PERFORM xera_accept_miner_agreement(g, v, repeat('e',64)); END LOOP; END \$\$" >/dev/null

TMP=$(mktemp -d)
par() {   # par <tag> <sql>...  runs each SQL in its own psql session at the same time
  local tag=$1; shift; local i=0
  for sql in "$@"; do i=$((i+1)); ( psql -At -q -d "$DB" -c "$sql" > "$TMP/$tag.$i" 2>&1 ) & done
  wait
}

echo "== 1. same user, 8 simultaneous starts"
S=(); for i in 1 2 3 4 5 6 7 8; do S+=("SELECT xera_start_mining_launch(1, 24, 5000)->>'bonus_status'"); done
par one "${S[@]}"
OK=$(cat $TMP/one.* | grep -cE "^(GRANTED|ALREADY_RECEIVED|SLOTS_FULL|DISABLED|SKIPPED)")
DUP=$(cat $TMP/one.* | grep -c "active_session_exists")
expect "exactly one start succeeded" "$OK" "1"
expect "the other 7 were rejected as active_session_exists" "$DUP" "7"
expect "one active session" "$(q "SELECT COUNT(*) FROM xera_mining_sessions WHERE user_id=1")" "1"
expect "one bonus for that user" "$(q "SELECT COUNT(*) FROM xera_transactions WHERE user_id=1 AND type='BONUS'")" "1"

echo "== 2. six users race for the last 2 bonus slots"
q "UPDATE xera_launch_state SET bonus_slots_used = 98, bonus_distributed = 9800" >/dev/null
q "UPDATE xera_mining_sessions SET status='CANCELLED'" >/dev/null
S=(); for u in 11 12 13 14 15 16; do S+=("SELECT xera_start_mining_launch($u, 24, 5000)->>'bonus_status'"); done
par two "${S[@]}"
expect "exactly 2 GRANTED" "$(cat $TMP/two.* | grep -c '^GRANTED$')" "2"
expect "4 SLOTS_FULL" "$(cat $TMP/two.* | grep -c '^SLOTS_FULL$')" "4"
expect "all 6 sessions started" "$(q "SELECT COUNT(*) FROM xera_mining_sessions WHERE user_id BETWEEN 11 AND 16")" "6"
expect "slots end at exactly 100" "$(q "SELECT bonus_slots_used FROM xera_launch_state")" "100"
expect "bonus total never above 10000" "$(q "SELECT bonus_distributed FROM xera_launch_state")" "10000.0000"
expect "distinct slot numbers 99 and 100" "$(q "SELECT string_agg(slot_number::text, ',' ORDER BY slot_number) FROM xera_early_miner_bonuses WHERE user_id BETWEEN 11 AND 16")" "99,100"
expect "wallet total = ledger (bonus only)" "$(q "SELECT (SELECT COALESCE(SUM(cached_balance),0) FROM xera_wallets WHERE user_id BETWEEN 11 AND 16) = (SELECT COALESCE(SUM(amount),0) FROM xera_transactions WHERE user_id BETWEEN 11 AND 16 AND type='BONUS')")" "t"

echo "== 3. tier boundary: 99 active miners, 4 start at once"
q "UPDATE xera_mining_sessions SET status='CANCELLED'" >/dev/null
q "INSERT INTO xera_mining_sessions (user_id, expires_at, rate_snapshot, estimated_reward) SELECT g, now()+interval '12 hours', 10, 10 FROM generate_series(1000,1098) g" >/dev/null
expect "99 active before" "$(q "SELECT xera_active_miner_count()")" "99"
S=(); for u in 1500 1501 1502 1503; do S+=("SELECT xera_start_mining_launch($u, 24, 5000)->>'rate_snapshot'"); done
par three "${S[@]}"
expect "exactly one miner earns 10" "$(cat $TMP/three.* | grep -c '^10.0000$')" "1"
expect "three miners earn 8" "$(cat $TMP/three.* | grep -c '^8.0000$')" "3"
expect "103 active after (99 + 4 new)" "$(q "SELECT xera_active_miner_count()")" "103"

echo "== 4. same user, 6 simultaneous daily claims"
S=(); for i in 1 2 3 4 5 6; do S+=("SELECT reward_credited FROM xera_claim_daily_reward(1700, 2)"); done
D0=$(q "SELECT mining_distributed FROM xera_allocations WHERE id=1")
par four "${S[@]}"
expect "exactly one claim paid" "$(cat $TMP/four.* | grep -cE '^2(\.0+)?$')" "1"
expect "balance is 2, not 12" "$(q "SELECT cached_balance FROM xera_wallets WHERE user_id=1700")" "2.0000"
expect "pool moved by exactly 2" "$(q "SELECT mining_distributed - $D0 FROM xera_allocations WHERE id=1")" "2.0000"

echo "== 5. no negative balances / allocation within limit"
expect "no negative wallets" "$(q "SELECT COUNT(*) FROM xera_wallets WHERE cached_balance < 0")" "0"
expect "allocation not exceeded" "$(q "SELECT mining_distributed <= mining_allocation FROM xera_allocations WHERE id=1")" "t"

rm -rf "$TMP"; dropdb --if-exists "$DB" >/dev/null 2>&1
echo; [ $FAILS -eq 0 ] && echo "ALL CONCURRENCY TESTS PASSED" || { echo "$FAILS FAILURE(S)"; exit 1; }
