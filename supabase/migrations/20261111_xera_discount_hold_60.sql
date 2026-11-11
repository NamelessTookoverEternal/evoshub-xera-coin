-- XERA data discount: hold the buyer's XERA for 60 minutes instead of 30. Safe to re-run.
ALTER TABLE xera_discount_config ALTER COLUMN hold_minutes SET DEFAULT 60;
UPDATE xera_discount_config SET hold_minutes = 60, updated_at = now() WHERE id = 1;
