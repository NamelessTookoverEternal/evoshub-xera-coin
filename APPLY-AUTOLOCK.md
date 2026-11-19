# Auto-lock + Overview flagged-wallets alert

1. Supabase SQL Editor: run supabase/migrations/20261119_xera_p2p_autolock_v4.sql once (safe to re-run).
   Check: SELECT auto_lock_enabled FROM xera_p2p_config;   -- false
2. Copy the files over the same paths. Redeploy Render (backend), then the frontend.
3. Admin console > XERA P2P review > Auto-lock. It starts OFF. Turn it on when you are ready.

Locked = cannot send (P2P) or withdraw (on-chain claim). Can still sign in, see balance, mine, receive, contact support.
Both sides are locked on any flag: the flagged wallet and the senders involved.
Unlock button per account (reason required), optional "false flag" reward credited to Pure XERA.
Overview: "Flagged wallets" and "Locked accounts" cards, attention lines, and a badge on XERA P2P review.
