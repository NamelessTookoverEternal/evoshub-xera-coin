# XERA P2P (in-app transfers) - everything is ready-made

Copy the folders in this package over your repo root (evoshub-main). Same paths as the repo.

NEW files:
  supabase/migrations/20261116_xera_p2p_v1.sql   (run in Supabase SQL Editor; needs 20261107 data-discount migration applied)
  python/xera/p2p.py
  hub-frontend/src/pages/xera-transfer.html
  hub-frontend/src/js/xera-transfer.js
  hub-frontend/src/js/xera-id.js                 (shows your XERA ID on Profile + Wallet tabs)

CHANGED files (overwrite; each differs from your original by 1-5 lines only):
  python/main.py                          + import and include_router for the P2P routes
  hub-frontend/vite.config.js             + builds the xera-transfer page
  hub-frontend/vercel.json                + /xera-transfer rewrite   (this fixes the 404)
  hub-frontend/netlify.toml               + /xera-transfer redirect  (this fixes the 404)
  hub-frontend/src/pages/xera/index.html  XERA ID rows on Profile + Wallet tabs, AND the live Transfer chip.
                                          Safe to deploy early: until transfer_enabled = true the Transfer page says "not open yet".

Go-live order
1. Run the migration.
2. Deploy backend (python/main.py + python/xera/p2p.py).
3. Deploy frontend (new page + vite.config.js + vercel.json + netlify.toml). 
4. Open /xera-transfer directly - it should load (it says "not open yet" while transfers are off).
5. Test with two accounts: UPDATE xera_config SET transfer_enabled = true WHERE id = 1;
6. (If you held back index.html) deploy it so the ID rows and Transfer chip appear.
Limits: min 10, max 100 per transfer, 500 per rolling 24h (table xera_p2p_config).
