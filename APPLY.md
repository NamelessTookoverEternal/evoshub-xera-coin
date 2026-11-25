Steps 1 + 2 + 3 together (real-name rules, paid name change, account deletion).
Use THIS zip instead of the step 1 and step 2 zips: several files (main.py, routes_auth.py, xera.js,
xera/index.html) changed in more than one step, so this is the safe, complete set. Copy over your repo, same paths.

DATABASE (Supabase SQL Editor, run in this order, BEFORE deploying the backend)
  1. supabase/migrations/20261124_xera_name_change_v1.sql
  2. supabase/migrations/20261125_xera_account_deletion_v1.sql

BACKEND (Render)
  NEW      python/xera/name_rules.py
  NEW      python/xera/name_change.py
  NEW      python/xera/routes_admin_name_change.py
  NEW      python/xera/account_deletion.py
  NEW      python/xera/routes_admin_account_deletion.py
  NEW      python/tests/test_account_deletion.py
  CHANGED  python/main.py                          +4 imports, +4 include_router lines
  CHANGED  python/xera/routes_auth.py              real-name check on signup; after a XERA sign-in the deletion sweep runs
  CHANGED  python/xera/routes_admin_vaults.py      "Name change vault" card
  CHANGED  python/services/evosdata/core.py        real-name check on EVOS Data signup

FRONTEND
  NEW      hub-frontend/src/js/xera-name-change.js
  NEW      hub-frontend/src/js/xera-account-deletion.js
  CHANGED  hub-frontend/src/js/xera.js
  CHANGED  hub-frontend/src/js/hub-login.js
  CHANGED  hub-frontend/src/pages/login.html
  CHANGED  hub-frontend/src/pages/xera/index.html

SETTINGS (SQL)
  UPDATE xera_name_change_config SET fee = 150 WHERE id = 1;            -- name change fee (default 100)
  UPDATE xera_name_change_config SET enabled = false WHERE id = 1;      -- pause name changes
  UPDATE xera_account_deletion_config SET grace_days = 14 WHERE id = 1; -- waiting period (default 7)
  UPDATE xera_account_deletion_config SET enabled = false WHERE id = 1; -- pause new deletion requests

WHEN DOES A DELETION FINISH?
  After the 7 days, the next time anyone signs in to XERA the app finishes all due deletions. You can also
  finish them yourself (admin): POST /api/admin/xera/account-deletion/run, and see the list with GET on the same path.
  Optional: set the Render env var ACCOUNT_DELETION_CRON_KEY and have any outside scheduler call
  POST /api/xera/account-deletion/sweep with header X-Cron-Key: <that value> once a day.
