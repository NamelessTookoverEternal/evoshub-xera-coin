# Spin to Win + Become-Agent fee

## Deploy checklist
1. Run `supabase/migrations/20261013_spin_and_agent_fee.sql` in Supabase (safe to re-run).
2. Deploy the backend (new files: `spin.py`, `agent_fee.py`; edited: `main.py`). No new env vars.
   Optional: `SPIN_DAILY_CAP_GB` (default 50).
3. Deploy the frontend (`evos-frontend`).
4. **Everyone must sign in once more.** Login now issues a signed `user_token`; Spin and Become Agent need it.
   Pages tell a customer with an old session to sign out and in again.
5. Do one real GH₵50 payment on your own account to test the agent flow end to end (account upgrades ~30 min later),
   and one real spin win claimed to your own number.

## Spin to Win (`spin.py`)
- One spin per user per UTC day (midnight Ghana time), enforced by a unique constraint.
- Wheel: 1GB, Try again, 2GB, Try again ... 10GB, Try again. Server picks the result.
- Odds per spin: normal 1GB 1%, 2GB 0.5%, 3GB 0.4%, 4GB 0.3%, 5GB 0.25%, 6GB 0.2%, 7GB 0.15%, 8GB 0.12%, 9GB 0.1%, 10GB 0.05% (about 1 in 2,000).
  After buying 3GB or more (paid order, last 48h, used once): 1GB becomes 25%, the rest unchanged. The boost is never shown to users.
  Change `PRIZE_ODDS` at the top of `spin.py`.
- Daily cap: 50GB given away per day. After that the wheel only lands on Try again until the next day.
- A win pops up with confetti and asks for phone number + network. Telecel/Vodafone is greyed out unless the prize is 10GB
  (checked on the server too). A network is also greyed out if you don't sell that size on it in `prices`.
- Unclaimed wins can be claimed for 7 days (the popup reopens from the Spin page).
- Claiming creates a normal order (`source='spin'`, price 0) and sends it to the first provider in `provider_routes`.
  If that fails the order stays `processing` with no provider ref, and your existing `retry_stuck_orders()` takes over after 10 minutes.
- Sidebar and phone menu: "Spin to Win". A friendly popup appears once per session at a random moment (12-40s), and the order-success page shows a spin offer.

## Become Agent (`agent_fee.py`)
- Page `/become-agent`: GH₵100 crossed out, GH₵50, paid on Paystack. The amount is set by the server.
- After payment the server waits 30 minutes (from Paystack's paid time), verifies with Paystack again, then sets
  `users.role='agent'`, `agent_status='approved'`. A background job (every minute) does this, so closing the page is fine.
- Activation is an atomic claim (exactly once). Underpaid, failed or never-paid attempts never activate (unpaid ones expire after 24h).
- The page hands the new agent their agent token, so no extra sign-in is needed.

## Security note
User tokens are signed with a different prefix from agent tokens, so a customer token can never open `/agent/*` routes.

## Tests
`python test_spin_agent_fee.py` (65 checks, fake database). `test_dashxera.py` and `test_evoxera_bot.py` still pass.
