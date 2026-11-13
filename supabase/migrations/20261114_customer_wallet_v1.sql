-- EVOS Data CUSTOMER wallet (v1): deposit-only, separate from the agent wallet.
-- Customers can top up and buy; there is no withdrawal and no link to agent_wallets (no cross-buying at agent prices).

CREATE TABLE IF NOT EXISTS customer_wallets (
  user_id    BIGINT PRIMARY KEY,
  balance    NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS customer_wallet_transactions (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL,
  type       TEXT NOT NULL CHECK (type IN ('credit','debit')),
  amount     NUMERIC(14,2) NOT NULL CHECK (amount > 0),
  reference  TEXT NOT NULL,
  note       TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cwt_ref_type ON customer_wallet_transactions (reference, type);
CREATE INDEX IF NOT EXISTS ix_cwt_user ON customer_wallet_transactions (user_id, id DESC);

CREATE TABLE IF NOT EXISTS customer_wallet_deposits (
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL,
  reference    TEXT NOT NULL UNIQUE,
  amount       NUMERIC(14,2) NOT NULL CHECK (amount > 0),   -- what the wallet receives
  total_charge NUMERIC(14,2) NOT NULL,                      -- what Paystack charges (no extra fee: equals amount)
  status       TEXT NOT NULL DEFAULT 'pending',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Admin-editable wallet discount (GH₵ off every order paid from the wallet).
CREATE TABLE IF NOT EXISTS customer_wallet_settings (
  id           INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  discount_ghs NUMERIC(8,2) NOT NULL DEFAULT 0.10 CHECK (discount_ghs >= 0)
);
INSERT INTO customer_wallet_settings (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION customer_wallet_credit(p_user_id BIGINT, p_amount NUMERIC, p_reference TEXT, p_note TEXT DEFAULT NULL)
RETURNS NUMERIC LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_bal NUMERIC;
BEGIN
  IF p_amount IS NULL OR p_amount <= 0 THEN RAISE EXCEPTION 'invalid_amount'; END IF;
  PERFORM pg_advisory_xact_lock(7002, p_user_id::int);
  INSERT INTO customer_wallets (user_id) VALUES (p_user_id) ON CONFLICT DO NOTHING;
  IF EXISTS (SELECT 1 FROM customer_wallet_transactions WHERE reference = p_reference AND type = 'credit') THEN
    SELECT balance INTO v_bal FROM customer_wallets WHERE user_id = p_user_id; RETURN v_bal;
  END IF;
  UPDATE customer_wallets SET balance = balance + p_amount, updated_at = now() WHERE user_id = p_user_id RETURNING balance INTO v_bal;
  INSERT INTO customer_wallet_transactions (user_id, type, amount, reference, note) VALUES (p_user_id, 'credit', p_amount, p_reference, p_note);
  RETURN v_bal;
END $$;

-- Debit + order in ONE transaction. Raises insufficient_balance (P0010) when short.
CREATE OR REPLACE FUNCTION customer_wallet_purchase(p_user_id BIGINT, p_price NUMERIC, p_reference TEXT, p_network TEXT, p_bundle TEXT, p_phone TEXT)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_bal NUMERIC; v_order orders%ROWTYPE;
BEGIN
  IF p_price IS NULL OR p_price <= 0 THEN RAISE EXCEPTION 'invalid_amount'; END IF;
  PERFORM pg_advisory_xact_lock(7002, p_user_id::int);
  SELECT * INTO v_order FROM orders WHERE paystack_ref = p_reference LIMIT 1;
  IF FOUND THEN
    SELECT balance INTO v_bal FROM customer_wallets WHERE user_id = p_user_id;
    RETURN jsonb_build_object('order_id', v_order.id, 'balance', COALESCE(v_bal,0), 'replayed', true);
  END IF;
  INSERT INTO customer_wallets (user_id) VALUES (p_user_id) ON CONFLICT DO NOTHING;
  SELECT balance INTO v_bal FROM customer_wallets WHERE user_id = p_user_id FOR UPDATE;
  IF v_bal < p_price THEN RAISE EXCEPTION 'insufficient_balance' USING ERRCODE = 'P0010'; END IF;
  UPDATE customer_wallets SET balance = balance - p_price, updated_at = now() WHERE user_id = p_user_id RETURNING balance INTO v_bal;
  INSERT INTO orders (user_id, network, bundle, price, phone_number, paystack_ref, evosdata_ref, status)
  VALUES (p_user_id, p_network, p_bundle, p_price, p_phone, p_reference, p_reference, 'paid') RETURNING * INTO v_order;
  INSERT INTO customer_wallet_transactions (user_id, type, amount, reference, note)
  VALUES (p_user_id, 'debit', p_price, p_reference, p_bundle || ' ' || p_network || ' to ' || p_phone);
  RETURN jsonb_build_object('order_id', v_order.id, 'balance', v_bal, 'replayed', false);
END $$;

-- A wallet order that ends up failed is refunded (and its XERA returned) automatically, whichever code path failed it.
CREATE OR REPLACE FUNCTION customer_wallet_order_failed_refund() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NEW.paystack_ref LIKE 'EVOS-WLT-%' THEN
    PERFORM customer_wallet_credit(NEW.user_id, NEW.price, 'refund:' || NEW.paystack_ref, 'Refund: order failed');
    IF to_regprocedure('xera_discount_refund(text)') IS NOT NULL THEN
      EXECUTE 'SELECT xera_discount_refund($1)' USING NEW.paystack_ref;
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_wallet_order_failed_refund ON orders;
CREATE TRIGGER trg_wallet_order_failed_refund AFTER UPDATE OF status ON orders
  FOR EACH ROW WHEN (NEW.status = 'failed' AND OLD.status IS DISTINCT FROM 'failed')
  EXECUTE FUNCTION customer_wallet_order_failed_refund();

-- service_role only (the API); nobody reaches these from the browser.
ALTER TABLE customer_wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_wallet_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_wallet_deposits ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_wallet_settings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON FUNCTION customer_wallet_credit(BIGINT,NUMERIC,TEXT,TEXT), customer_wallet_purchase(BIGINT,NUMERIC,TEXT,TEXT,TEXT,TEXT), customer_wallet_order_failed_refund() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION customer_wallet_credit(BIGINT,NUMERIC,TEXT,TEXT), customer_wallet_purchase(BIGINT,NUMERIC,TEXT,TEXT,TEXT,TEXT) TO service_role;
