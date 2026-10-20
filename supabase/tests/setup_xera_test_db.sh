#!/usr/bin/env bash
# Builds a DISPOSABLE Postgres database from the repo's real XERA migrations.
# Usage: ./setup_xera_test_db.sh [dbname]   (run as a user allowed to createdb/psql)
# NEVER point this at a real Supabase project: it drops the target database.
set -euo pipefail
DB="${1:-xera_launch_test}"
HERE="$(cd "$(dirname "$0")" && pwd)"
MIG="$HERE/../migrations"
PSQL="psql -v ON_ERROR_STOP=1 -q"

dropdb --if-exists "$DB"
createdb "$DB"
$PSQL -d "$DB" <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role BYPASSRLS; END IF;
END $$;
-- Minimal stand-in for the shared Hub users table (real one has many more columns).
CREATE TABLE users (id BIGSERIAL PRIMARY KEY, username TEXT, full_name TEXT, email TEXT, referral_code TEXT, referred_by TEXT);
-- Stand-in for Supabase auth.users used by admin_agents FKs, if a migration needs it.
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (id UUID PRIMARY KEY DEFAULT gen_random_uuid());
SQL

for f in 20260901_xera_token_v1 20260904_daily_claim_and_ecosystem 20260912_xera_blockchain_v1 \
         20260914_xera_blockchain_hardening 20260923_xera_hashrate_v1 20260930_xera_referrals_v1 \
         20261003_xera_wallet_connection_methods 20261006_xera_amount_claims; do
  echo "applying $f"
  $PSQL -d "$DB" -f "$MIG/$f.sql" >/dev/null
done
echo "baseline schema ready in $DB"
