# Account deletion v2 (wallet review popup) + EVOSGPT sign-in fix

Copy these files over your project (same paths). Nothing else changed.

## Order
1. Supabase SQL Editor: run `supabase/migrations/20261126_xera_account_deletion_wallets_v2.sql`
   (the earlier 20261125 deletion SQL must already be run; this one is safe to run twice).
2. Deploy the backend on Render.
3. Deploy the frontend (Hub frontend and EVOSGPT frontend).

Run the SQL BEFORE the backend. If it is missing, "Delete" shows "Could not check your wallets right now" and nothing is scheduled.

## What the user sees
1. Popup 1 (as before): warnings, password, tick box, Delete.
2. Popup 2: XERA, EVOS Data (customer wallet, plus agent wallet for agents) and EVOSGPT with real balances.
   Money that will be lost is red. Buttons: Cancel / Proceed to delete.
3. If any balance would be lost, one more warning ("Last warning"). Go back / Yes, delete and lose it.
4. Only then is the deletion scheduled (7 days, cancellable from the same card).

## Rules worth knowing
- Money sitting in a wallet never blocks deletion; it is shown in red and warned twice. This applies to GHS and to Pure XERA.
- Money that is MOVING does block: an EVOS Data order being delivered (paid/processing) or an agent withdrawal in progress.
  Checked again on day 7; if one appears during the wait, the deletion waits.
- The server re-checks: the second warning must have been accepted, and the balances must still match what the popup showed
  (if a top-up arrived meanwhile, popup 2 reloads with the new numbers).
- On day 7: EVOS Data wallets are set to 0 (ledger row `deletion:<id>`), password-reset codes deleted, AFA personal fields erased,
  EVOSGPT chats / memory summary / daily counts / usage deleted, EVOSGPT images and documents erased from storage.
  Kept: EVOS Data orders and transactions, EVOSGPT shared knowledge (has no user id).
- Not handled: a Paystack top-up still pending at the moment of deletion would credit an already-emptied wallet.

## EVOSGPT sign-in fix (api/index.js, App.jsx)
Inside the Hub, EVOSGPT now uses the live Hub token first, asks the Hub for a fresh session every time it opens (replacing any
saved user, including another account), shows "Signing you in..." instead of bouncing to login while that runs, and retries once
with the other saved token before sending the person to login. EVOS Data has its own Hub-session code, not checked here.
