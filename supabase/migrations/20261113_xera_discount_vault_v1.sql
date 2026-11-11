-- ============================================================================
-- XERA DISCOUNT VAULT (look-only)                                  2026-11-13
--
-- The "vault" is the running total of XERA that customers spent on discounts.
-- It is READ-ONLY: it is computed live from the existing ledger
-- (xera_transactions, type DISCOUNT_SPEND, minus discount refunds), so
--   * nothing here moves a balance,
--   * it can never drift from the ledger,
--   * nobody can spend or withdraw from it (there is no wallet behind it).
-- If you later want to move XERA out of it, that needs its own audited function.
-- ============================================================================

CREATE OR REPLACE VIEW xera_discount_vault_deposits AS
SELECT
    t.id,
    t.reference_id AS order_ref,
    t.user_id,
    t.amount,
    t.created_at,
    EXISTS (
        SELECT 1 FROM xera_transactions r
         WHERE r.type = 'REVERSAL'
           AND r.reference_id = 'discount-refund:' || t.reference_id
    ) AS refunded
FROM xera_transactions t
WHERE t.type = 'DISCOUNT_SPEND' AND t.direction = 'DEBIT' AND t.status = 'CONFIRMED';

CREATE OR REPLACE FUNCTION xera_discount_vault_summary()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT jsonb_build_object(
        'balance',          COALESCE(SUM(amount) FILTER (WHERE NOT refunded), 0),
        'total_collected',  COALESCE(SUM(amount), 0),
        'total_refunded',   COALESCE(SUM(amount) FILTER (WHERE refunded), 0),
        'orders',           COUNT(*) FILTER (WHERE NOT refunded),
        'last_30_days',     COALESCE(SUM(amount) FILTER (WHERE NOT refunded AND created_at >= now() - interval '30 days'), 0),
        'first_deposit_at', MIN(created_at),
        'last_deposit_at',  MAX(created_at)
    )
    FROM xera_discount_vault_deposits;
$$;

-- Backend (service role) only. Never readable from the browser.
REVOKE ALL ON xera_discount_vault_deposits FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION xera_discount_vault_summary() FROM PUBLIC, anon, authenticated;
GRANT SELECT ON xera_discount_vault_deposits TO service_role;
GRANT EXECUTE ON FUNCTION xera_discount_vault_summary() TO service_role;
