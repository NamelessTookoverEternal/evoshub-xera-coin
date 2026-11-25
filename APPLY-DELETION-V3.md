# Account deletion v3: a stuck order no longer locks anyone out

Copy these files over your project (same paths). Nothing else changed.

## Order
1. Supabase SQL Editor: run `supabase/migrations/20261127_xera_account_deletion_stuck_orders_v3.sql`
   (run 20261125 and 20261126 first if you haven't). Safe to run twice. No old function is dropped.
2. Deploy the backend on Render.
3. Deploy the Hub frontend.

Run the SQL BEFORE the backend. If it is missing, the app still works as before: a stuck order simply keeps blocking, with the same message.

## What the user sees
1. Popup 1: password + tick box, press Delete.
2. If an EVOS Data order (paid / processing) or agent withdrawal (processing) is in progress:
   the red notice shows once, with "If it looks stuck, press Delete again to continue anyway."
3. Press Delete again: popup 2 opens (XERA, EVOS Data, EVOSGPT wallets and balances), with a red box at the top saying
   the order/withdrawal is still in progress and stays on record.
4. Proceed to delete -> last warning if money would be lost -> deletion scheduled for 7 days.

## Rules
- Only this one blocker is skipped. Suspended wallet, money lock, on-chain claim, XERA data order and KYC in review still block.
- The choice is saved on the deletion row (`ignore_evosdata_busy`), so day 7 does not wait for the stuck order either.
  Without the choice (older requests) day 7 still waits for it, as before.
- The Delete button on the Profile card is no longer greyed out because of a stuck order.
- The second press is sent by the popup. The server skips the check only when the request says so; the password is still checked every time.
