# XERA P2P (in-app transfers) - what to apply

Copy these folders into the repo root (evoshub-main). All files are NEW.

  supabase/migrations/20261116_xera_p2p_v1.sql   -> run in Supabase SQL Editor (needs 20261107 data-discount migration already applied)
  python/xera/p2p.py                             -> backend routes
  hub-frontend/src/pages/xera-transfer.html      -> send page + public ledger
  hub-frontend/src/js/xera-transfer.js

## Edits to existing files

READY-MADE: hub-frontend/src/pages/xera/index.html is included as a changed copy (Transfer chip made live) - just overwrite. Do it LAST, after transfer_enabled = true. Only 2 manual edits remain: main.py and vite.config.js (below).

1) python/main.py  - add next to the other `from xera...` imports (~line 35):
   from xera.p2p import router as xera_p2p_router
   and next to the other include_router lines (~line 142):
   app.include_router(xera_p2p_router, prefix="/api/xera/transfer", tags=["xera-p2p"])

2) hub-frontend/vite.config.js - add in the `input` list, next to xeraWallet:
   xeraTransfer:      'src/pages/xera-transfer.html',

3) hub-frontend/src/pages/xera/index.html (GO-LIVE SWITCH - do last, after transfer_enabled = true)
   Replace the Transfer "SOON" chip (~lines 217-219 and ~370) with:
   <a class="chip" href="/xera-transfer" style="text-decoration:none;color:inherit">
     <svg viewBox="0 0 24 24" fill="none"><path d="M7 10l-4 4 4 4M3 14h13M17 4l4 4-4 4M21 8H8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
     <span>Transfer</span>
   </a>

## Go-live order
1. Run the migration  2. Deploy backend (+main.py lines)  3. Deploy frontend (+vite line)
4. Test with two accounts  5. UPDATE xera_config SET transfer_enabled = true WHERE id = 1;  6. Swap the chip.
Limits: min 10, max 100 per transfer, 500 per rolling 24h (table xera_p2p_config).
