# XERA P2P - complete package (v1 + v2). Copy these folders over your repo root (evoshub-main).

NEW files
  supabase/migrations/20261116_xera_p2p_v1.sql          run FIRST in Supabase SQL Editor (needs 20261107 data-discount migration)
  supabase/migrations/20261118_xera_p2p_fee_flags_v2.sql run SECOND (fee for incomplete senders, IP/VPN columns, flagged-wallet review)
  python/xera/p2p.py
  python/xera/ipcheck.py                                  optional VPN lookup (off until you set the 2 Render env vars)
  python/xera/routes_admin_p2p.py                         admin endpoints
  hub-frontend/src/pages/xera-transfer.html
  hub-frontend/src/js/xera-transfer.js
  hub-frontend/src/js/xera-id.js                          XERA ID on Profile + Wallet tabs
  hub-frontend/src/pages/admin-xera-p2p.html              admin review page  ->  open /admin-xera-p2p.html
  hub-frontend/src/js/admin-xera-p2p.js

CHANGED files (overwrite; small diffs only)
  python/main.py                           P2P + admin P2P routers registered
  hub-frontend/vite.config.js              builds the transfer page and the admin page
  hub-frontend/vercel.json                 /xera-transfer rewrite
  hub-frontend/netlify.toml                /xera-transfer redirect
  hub-frontend/src/pages/xera/index.html   XERA ID rows + live Transfer chip

THE RULES NOW
  * Sender completed every step (KYC + $1 first-transfer fee): free, daily cap 500.
  * Sender NOT complete: may send, pays 50% extra (sender pays amount + fee, recipient gets the full amount), daily cap 100.
  * Per transfer: min 10, max 100 (cap counts amounts, not fees).
  * The fee is not paid to any wallet: it is debited, recorded as P2P_FEE, and shown as a look-only total on the admin page
    (same idea as the discount vault).
  * Every transfer stores the sender's IP and (if the checker is on) a VPN note.
  * Admin page flags wallets that got XERA from 3+ unverified accounts in 7 days, or from accounts sharing an IP.
  * All numbers (fee %, caps, min/max, flag thresholds) are editable on the admin page.

OPTIONAL: VPN CHECK (Render env vars; never paste keys in chat)
  XERA_IP_INTEL_PROVIDER=proxycheck
  XERA_IP_INTEL_API_KEY=<your proxycheck.io key>
  Also set TRUST_PROXY_HEADERS=true on Render if it is not already, otherwise the recorded IP is Render's proxy, not the user's.

GO-LIVE ORDER
  1. Run migration v1, then v2.      2. Deploy backend.      3. Deploy frontend.
  4. Open /xera-transfer directly: it says "not open yet".
  5. Test with two accounts, then: UPDATE xera_config SET transfer_enabled = true WHERE id = 1;
