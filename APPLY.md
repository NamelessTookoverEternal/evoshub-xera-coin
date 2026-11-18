# XERA P2P - complete package (v1 + v2). Copy these folders over your repo root (evoshub-main).

NEW files
  supabase/migrations/20261116_xera_p2p_v1.sql           run FIRST in Supabase SQL Editor (needs the 20261107 data-discount migration)
  supabase/migrations/20261118_xera_p2p_fee_flags_v2.sql run SECOND (fee for incomplete senders, IP/VPN columns, flagged-wallet review)
  python/xera/p2p.py
  python/xera/ipcheck.py                                  optional VPN lookup (off until you set 2 Render env vars)
  python/xera/routes_admin_p2p.py                         admin endpoints
  hub-frontend/src/pages/xera-transfer.html
  hub-frontend/src/js/xera-transfer.js
  hub-frontend/src/js/xera-id.js                          XERA ID on Profile + Wallet tabs
  hub-frontend/src/js/admin-console-p2p.js                the admin console "XERA P2P review" tab

CHANGED files (overwrite; small diffs only)
  python/main.py                                  P2P + admin P2P routers registered
  hub-frontend/vite.config.js                     builds the transfer page
  hub-frontend/vercel.json                        /xera-transfer rewrite
  hub-frontend/netlify.toml                       /xera-transfer redirect
  hub-frontend/src/pages/xera/index.html          XERA ID rows + live Transfer chip
  hub-frontend/src/js/admin-console.js            adds the "XERA P2P review" menu item (2 lines)
  hub-frontend/src/pages/admin-website-chat.html  adds the P2P tab panel (after the KYC panel)

THE RULES
  * Sender completed every step (KYC + $1 first-transfer fee): free, daily cap 500.
  * Sender NOT complete: may send, pays 50% extra (sender pays amount + fee, recipient gets the full amount), daily cap 100.
  * Per transfer: min 10, max 100 (caps count amounts, not fees).
  * The fee goes to no wallet: it is debited, recorded as P2P_FEE, and shown as a look-only total in the admin tab.
  * Every transfer stores the sender's IP and (if the checker is on) a VPN note.
  * Admin tab flags wallets that got XERA from 3+ unverified accounts in 7 days, or from accounts sharing an IP.
  * All numbers are editable in the admin tab (Limits and fee); each change is saved in the admin log.

OPTIONAL: VPN CHECK (Render env vars; never paste keys in chat)
  XERA_IP_INTEL_PROVIDER=proxycheck
  XERA_IP_INTEL_API_KEY=<your proxycheck.io key>
  Also set TRUST_PROXY_HEADERS=true on Render if it is not already, otherwise the recorded IP is Render's proxy, not the user's.

GO-LIVE ORDER
  1. Run migration v1, then v2.   2. Deploy backend.   3. Deploy frontend.
  4. Open /xera-transfer directly: it says "not open yet".   5. Admin console -> XERA P2P review should load.
  6. Test with two accounts, then: UPDATE xera_config SET transfer_enabled = true WHERE id = 1;
