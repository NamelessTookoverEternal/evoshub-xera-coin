#!/usr/bin/env bash
# Real concurrency test for the global mining cap — fires two genuinely
# parallel Postgres sessions (BNB + TON) whose combined amount would push
# the global total over 75,000,000, and asserts EXACTLY ONE succeeds.
#
# Usage: PGPASSWORD=... ./run_concurrency_test.sh <host> <db> <user>
set -euo pipefail

HOST="${1:-localhost}"
DB="${2:-xera_test}"
USER_="${3:-postgres}"

psql -h "$HOST" -U "$USER_" -d "$DB" -c "
  DELETE FROM xera_onchain_claims WHERE reference_id IN ('concurrency-bnb', 'concurrency-ton');
  UPDATE xera_mining_allocation_state SET global_reserved_amount = 70000000;
  DELETE FROM users WHERE id IN (991, 992);
  INSERT INTO users (id, username) VALUES (991, 'race-bnb'), (992, 'race-ton');
" > /dev/null

RACE1=$(mktemp)
RACE2=$(mktemp)
echo "SELECT (xera_reserve_onchain_claim('concurrency-bnb', 991, 'BNB', '0xrace1', 4000000, 1000000, 3000000, '0xdist', now() + interval '1 hour')).status;" > "$RACE1"
echo "SELECT (xera_reserve_onchain_claim('concurrency-ton', 992, 'TON', 'EQrace2', 4000000, 1000000, 3000000, 'EQdist', now() + interval '1 hour')).status;" > "$RACE2"

OUT1=$(mktemp)
OUT2=$(mktemp)

( psql -h "$HOST" -U "$USER_" -d "$DB" -f "$RACE1" > "$OUT1" 2>&1 & )
( psql -h "$HOST" -U "$USER_" -d "$DB" -f "$RACE2" > "$OUT2" 2>&1 & )
wait
sleep 1

SUCCESSES=0
grep -q "SIGNED" "$OUT1" && SUCCESSES=$((SUCCESSES + 1))
grep -q "SIGNED" "$OUT2" && SUCCESSES=$((SUCCESSES + 1))

FINAL=$(psql -h "$HOST" -U "$USER_" -d "$DB" -t -c "SELECT global_reserved_amount FROM xera_mining_allocation_state WHERE id = 1;" | tr -d ' ')

echo "--- race 1 (BNB) output ---"; cat "$OUT1"
echo "--- race 2 (TON) output ---"; cat "$OUT2"
echo "successes: $SUCCESSES, final global_reserved_amount: $FINAL"

if [ "$SUCCESSES" -ne 1 ]; then
  echo "CONCURRENCY TEST FAILED: expected exactly 1 success, got $SUCCESSES"
  exit 1
fi
if [ "$FINAL" != "74000000.0000" ]; then
  echo "CONCURRENCY TEST FAILED: expected final global_reserved_amount = 74000000.0000, got $FINAL"
  exit 1
fi

echo "PASS: exactly one of two concurrent BNB+TON reservations succeeded; global total never exceeded the cap."
rm -f "$RACE1" "$RACE2" "$OUT1" "$OUT2"
