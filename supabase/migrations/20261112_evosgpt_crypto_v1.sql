-- ============================================================
-- EVOSGPT plans: pay with USDT (BEP-20) via NOWPayments
-- ============================================================
-- Additive only. Safe to re-run. Run it BEFORE turning EVOSGPT crypto on.
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> paste -> Run.
--
--   payment_method    'paystack' (default, every existing row) or 'crypto'
--   crypto_usd_cents  the USD charge fixed at purchase (rounded up); the IPN is checked against it
-- ============================================================

ALTER TABLE evosgpt_purchases ADD COLUMN IF NOT EXISTS payment_method   TEXT NOT NULL DEFAULT 'paystack';
ALTER TABLE evosgpt_purchases ADD COLUMN IF NOT EXISTS crypto_usd_cents INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'evosgpt_purchases_method_chk') THEN
        ALTER TABLE evosgpt_purchases
            ADD CONSTRAINT evosgpt_purchases_method_chk CHECK (payment_method IN ('paystack', 'crypto'));
    END IF;
END $$;

-- CHECKS (run after):
--   select payment_method, count(*) from evosgpt_purchases group by 1;   -- existing rows show 'paystack'
