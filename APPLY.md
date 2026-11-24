Step 1: real-name rules + signup popup. Copy these files over your repo (same paths).

NEW      python/xera/name_rules.py            shared name rules (also used later by the paid name change)
CHANGED  python/xera/routes_auth.py           Hub/XERA signup checks the name (+1 import, +5 lines in xera_register)
CHANGED  python/services/evosdata/core.py     EVOS Data signup checks the name (+5 lines at the top of register)
CHANGED  hub-frontend/src/pages/login.html    "Full name" field removed from the form; real-name popup added
CHANGED  hub-frontend/src/js/hub-login.js     popup shown before the account is created

Deploy the backend (Render) and the frontend. No database change.
Existing users are not affected. Only new signups.
