# Withdraw to a manually added wallet address (BNB), v1

Users can now add a BNB address by hand and withdraw XERA to it, without the "Connect wallet and sign" step.
The user's own wallet still sends the transaction and pays the BNB gas. No relayer, no contract change.

## What the user sees
1. **Add address.** The form now says that a new or changed address waits 12 hours, that each withdrawal asks for the password, and that a wrong address cannot be recovered.
2. **Safety wait.** The wallet card shows "you can withdraw to this address in 11 h 20 min", then "ready".
3. **Withdraw.** A popup shows the full address with the first 6 and last 6 characters in green, the amount, a tick box ("I checked this address, it is my own wallet and it holds BNB") and a password field. Nothing is reserved until they confirm.
4. **Wallet check.** The wallet that opens must be the saved address. If it is a different account, the user gets a clear message and nothing is reserved. This is also the proof that they control the address.
5. **Gas check.** If the saved address has almost no BNB, the user is told before anything is reserved.
6. The existing KYC and first-transfer-fee checks run as before.

## Rules enforced on the server (not only in the popup)
- Password on every withdrawal (and every retry) to a manual address. 5 wrong passwords in 15 minutes blocks further tries for 15 minutes. A wrong password reserves nothing.
- 12-hour wait after adding or changing the address. Change it with `XERA_MANUAL_WALLET_COOLDOWN_SECONDS` on Render (seconds). If the time cannot be read, the withdrawal is refused.
- One address, one account (SQL). Saving the same address again does not restart the wait. A different address does.
- BNB only. TON manual addresses still cannot settle.
- A connected (signature-verified) wallet works exactly as before: no password, no wait.
- The claim code itself still refuses a manual address unless the route opts in after the password check.

## Deploy
1. Run `supabase/migrations/20261128_xera_manual_wallet_withdraw_v1.sql` in Supabase. Safe to run twice, drops nothing.
   If it prints a NOTICE that the unique index was not created, two accounts already hold the same typed address. Fix those and run it again.
2. Deploy the backend on Render.
3. Deploy the Hub frontend.
If the backend goes out before the SQL, everything works except the one-address-per-account rule.

## Files
- `supabase/migrations/20261128_xera_manual_wallet_withdraw_v1.sql`
- `python/xera/chain/claims.py`, `python/xera/chain/wallet_link.py`, `python/xera/routes_chain.py`
- `hub-frontend/src/js/xera-chain.js`
- `python/tests/test_manual_wallet_withdraw.py` (new, 15 tests), `python/tests/test_readiness.py` (one old test changed: it said a manual address could never settle)

## Not done / know this
- On-chain claiming for normal users still depends on `onchain_enabled` and your admin pilot setting. This change does not open it.
- Someone can type another person's address as their own manual address (nobody can stop that without a signature). The real owner can still connect and verify it. The worst case is a stranger sending their own XERA to that address.
- Tested here: backend tests, the SQL on a real Postgres, and the popup in a simulated browser. Not tested: a real wallet and a real BNB transaction. Try one small withdrawal on testnet first.
