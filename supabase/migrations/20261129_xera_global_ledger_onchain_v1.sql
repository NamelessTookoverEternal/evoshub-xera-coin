-- ============================================================
-- XERA global ledger: show confirmed on-chain claims next to Pure XERA transfers.
--
-- Adds ONE read-only view, xera_public_activity. It does not change xera_p2p_public_ledger
-- or any table. Public fields only: masked XERA ID, amount, time. No names, no user ids,
-- no wallet address, no transaction hash.
--   kind = 'p2p'     -> sender -> recipient, amount in Pure XERA
--   kind = 'onchain' -> sender = the claimer's masked ID, recipient is NULL,
--                       amount = the full amount claimed (before the 25/75 split)
-- Only CONFIRMED claims on MAINNET are listed (testnet and unconfirmed claims never appear).
-- Safe to re-run.
-- ============================================================
CREATE OR REPLACE VIEW xera_public_activity AS
SELECT 'p2p'::text                                             AS kind,
       t.id                                                    AS ref,
       left(t.sender_xera_id, 4)    || '…' || right(t.sender_xera_id, 3)    AS sender,
       left(t.recipient_xera_id, 4) || '…' || right(t.recipient_xera_id, 3) AS recipient,
       t.amount::numeric                                       AS amount,
       t.status::text                                          AS status,
       t.created_at                                            AS created_at
  FROM xera_p2p_transfers t
UNION ALL
SELECT 'onchain'::text,
       c.id,
       left(u.xera_id, 4) || '…' || right(u.xera_id, 3),
       NULL::text,
       c.claimed_amount::numeric,
       'CONFIRMED'::text,
       COALESCE(c.confirmed_at, c.created_at)
  FROM xera_onchain_claims c
  JOIN users u ON u.id = c.user_id
 WHERE c.status = 'CONFIRMED'
   AND c.network = 'mainnet'
   AND u.xera_id IS NOT NULL;

REVOKE ALL ON xera_public_activity FROM PUBLIC, anon, authenticated;
GRANT SELECT ON xera_public_activity TO service_role;
