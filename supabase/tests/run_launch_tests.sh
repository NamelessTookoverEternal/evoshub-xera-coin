#!/usr/bin/env bash
# Builds a disposable DB from the repo migrations and runs the launch SQL tests.
# Usage: ./run_launch_tests.sh [dbname]
set -euo pipefail
DB="${1:-xera_launch_test}"
HERE="$(cd "$(dirname "$0")" && pwd)"
"$HERE/setup_xera_test_db.sh" "$DB" >/dev/null 2>&1
psql -v ON_ERROR_STOP=1 -q -d "$DB" -f "$HERE/../migrations/20261020_xera_official_mining_rewards.sql" >/dev/null
psql -v ON_ERROR_STOP=1 -q -d "$DB" -f "$HERE/../migrations/20261021_xera_official_launch_v1.sql" >/dev/null 2>&1
psql -v ON_ERROR_STOP=1 -q -d "$DB" -f "$HERE/test_official_launch.sql"
