# XERA P2P update: 1% fee for verified senders (only the changed files, same repo paths)

NEW
  supabase/migrations/20261118_xera_p2p_verified_fee_v3.sql   run ONCE in Supabase SQL Editor (v1 and v2 already done - do NOT re-run them)

CHANGED (overwrite)
  python/xera/p2p.py                               /me reports the right fee for verified vs unverified
  python/xera/routes_admin_p2p.py                  admin can edit the verified fee
  hub-frontend/src/js/admin-console-p2p.js         admin tab shows + edits the verified fee
  hub-frontend/src/pages/admin-website-chat.html   adds the "Fee for verified senders (%)" box
  hub-frontend/src/pages/xera-transfer.html        wording ("pay a much lower fee")

THE RULES NOW
  * Every step complete (KYC + $1 first-transfer fee): 1% fee on top, daily cap 500.
  * Steps incomplete: 50% fee on top, daily cap 100.
  * Recipient always receives the full amount. Min 10 / max 100 per transfer.
  * All fees go to the look-only fee total (no wallet). Both percentages are editable in Admin console -> XERA P2P review -> Limits and fee.
  * The database refuses a verified fee higher than the unverified fee.

Verify after running v3:  SELECT verified_fee_bps, unverified_fee_bps FROM xera_p2p_config;   -- 100 / 5000
Deploy order: run v3, deploy backend, deploy frontend.
