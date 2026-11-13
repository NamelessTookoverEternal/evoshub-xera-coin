-- Records WHEN an order was delivered, whichever code path marked it successful (webhook, retry job, manual).
-- Feeds the live delivery estimate on the tracking page.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ;

CREATE OR REPLACE FUNCTION orders_stamp_delivered_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = 'successful' AND NEW.delivered_at IS NULL THEN
    NEW.delivered_at := now();
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_orders_stamp_delivered_at ON orders;
CREATE TRIGGER trg_orders_stamp_delivered_at BEFORE INSERT OR UPDATE OF status ON orders
  FOR EACH ROW EXECUTE FUNCTION orders_stamp_delivered_at();

CREATE INDEX IF NOT EXISTS ix_orders_delivered_recent ON orders (network, delivered_at DESC) WHERE delivered_at IS NOT NULL;
