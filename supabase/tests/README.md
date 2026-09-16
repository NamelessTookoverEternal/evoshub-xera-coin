# XERA blockchain hardening — SQL-level tests

These run against a **real, disposable Postgres database** — not mocks —
because the thing being tested (an atomic row-locked global counter,
Postgres role privileges) can't be meaningfully verified any other way.
All of these have been run and passed in this repository's sandbox against
Postgres 16.

## Setup (once per test database)

```bash
createdb xera_test
psql -d xera_test -c "
  DO \$\$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon; END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated; END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role BYPASSRLS; END IF;
  END \$\$;
  CREATE TABLE users (id BIGSERIAL PRIMARY KEY, username TEXT);
"
psql -d xera_test -f ../migrations/20260912_xera_blockchain_v1.sql
psql -d xera_test -f ../migrations/20260914_xera_blockchain_hardening.sql
```

A real Supabase project already has `anon`/`authenticated`/`service_role`
and its own `users`/`auth` tables — this setup block only exists to
reproduce that shape locally.

## Run

```bash
psql -d xera_test -f test_global_mining_cap.sql       # 9 sequential assertions (Phase 3 + 6)
PGPASSWORD=... ./run_concurrency_test.sh localhost xera_test postgres   # real parallel-session race (Phase 3)
PGPASSWORD=... ./run_privilege_test.sh localhost xera_test postgres    # Phase 7 privilege model
```

All three exit non-zero and print `FAILED` on any failure — wire into CI
as three separate steps against a fresh `xera_test` database (drop and
recreate between runs, since the SQL test file mutates state).

## What's NOT covered here

- `xera_expire_stale_onchain_claims()` (the deadline-sweep function) isn't
  exercised by an automated test — it was checked manually (a SIGNED row
  with `signature_deadline` in the past does transition to EXPIRED and
  releases its reserved amount on a manual call) but doesn't have a
  scripted assertion yet.
- RLS policies are "deny by default" (zero policies + RLS enabled) rather
  than real per-user row policies, because this app doesn't use Supabase
  Auth — see the migration file's own comment on this. If Supabase Auth is
  ever adopted, this test suite should grow real per-user policy tests.
