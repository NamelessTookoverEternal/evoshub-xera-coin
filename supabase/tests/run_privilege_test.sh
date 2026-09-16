#!/usr/bin/env bash
# Verifies the Phase 7 privilege model against a real Postgres instance
# with roles matching Supabase's (anon, authenticated, service_role).
set -uo pipefail  # no -e: we expect several commands to fail on purpose

HOST="${1:-localhost}"
DB="${2:-xera_test}"
USER_="${3:-postgres}"
FAIL=0

check_denied() {
  local desc="$1" sql="$2" role="$3"
  OUT=$(psql -h "$HOST" -U "$USER_" -d "$DB" -c "SET ROLE $role; $sql" 2>&1)
  if echo "$OUT" | grep -qi "permission denied"; then
    echo "PASS: $desc"
  else
    echo "FAIL: $desc — expected permission denied, got: $OUT"
    FAIL=1
  fi
}

check_allowed() {
  local desc="$1" sql="$2" role="$3"
  OUT=$(psql -h "$HOST" -U "$USER_" -d "$DB" -c "SET ROLE $role; $sql" 2>&1)
  if echo "$OUT" | grep -qi "permission denied"; then
    echo "FAIL: $desc — expected success, got permission denied"
    FAIL=1
  else
    echo "PASS: $desc"
  fi
}

check_denied "anon cannot read xera_onchain_claims directly" \
  "SELECT * FROM xera_onchain_claims;" anon

check_denied "anon cannot call xera_reserve_onchain_claim (impersonation)" \
  "SELECT xera_reserve_onchain_claim('priv-attack-1', 901, 'BNB', '0xhack', 100, 25, 75, '0xdist', now() + interval '1 hour');" anon

check_denied "authenticated cannot call xera_link_external_wallet for another user_id" \
  "SELECT xera_link_external_wallet(902, 'BNB', '0xstolen', 86400);" authenticated

check_denied "authenticated cannot directly UPDATE xera_mining_allocation_state" \
  "UPDATE xera_mining_allocation_state SET global_reserved_amount = 0;" authenticated

check_denied "anon cannot read xera_migration_snapshot directly" \
  "SELECT * FROM xera_migration_snapshot;" anon

check_allowed "service_role can call xera_reserve_onchain_claim" \
  "SELECT xera_reserve_onchain_claim('priv-ok-1', 901, 'BNB', '0xok', 10, 2.5, 7.5, '0xdist', now() + interval '1 hour');" service_role

check_allowed "service_role can read xera_onchain_claims directly" \
  "SELECT count(*) FROM xera_onchain_claims;" service_role

if [ "$FAIL" -ne 0 ]; then
  echo "PRIVILEGE HARDENING TEST FAILED"
  exit 1
fi
echo "ALL PRIVILEGE HARDENING TESTS PASSED"
