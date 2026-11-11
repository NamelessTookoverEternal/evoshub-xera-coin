-- ============================================================
-- Product switches: admin on/off control for each ecosystem product
-- ============================================================
-- Additive only. Safe to re-run.
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> paste -> Run.
--
--   enabled  = false  -> the product's tile is greyed out everywhere in the app.
--   enforce  = true   -> the backend ALSO refuses NEW orders / chats while it is off
--                        (EVOS Data and EVOSGPT). Payments already in progress,
--                        Paystack/provider webhooks and order-status checks keep working.
--   message           -> optional text shown when someone taps a greyed tile.
--
-- The table is closed to the browser: only the backend (service_role) reads or writes it,
-- and it checks the admin token plus a live admin_agents.is_active row on every change.
-- A missing row means the product is ON.
-- ============================================================

CREATE TABLE IF NOT EXISTS product_switches (
    product_key  TEXT PRIMARY KEY CHECK (product_key ~ '^[a-z0-9_]{2,40}$'),
    label        TEXT NOT NULL,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    enforce      BOOLEAN NOT NULL DEFAULT FALSE,
    message      TEXT CHECK (message IS NULL OR char_length(message) <= 200),
    updated_by   BIGINT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE product_switches ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON product_switches FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON product_switches TO service_role;

INSERT INTO product_switches (product_key, label, enabled, enforce) VALUES
    ('evosdata',  'EVOS Data',        TRUE, TRUE),
    ('evosgpt',   'EVOSGPT',          TRUE, TRUE),
    ('xera',      'XERA',             TRUE, FALSE),
    ('games',     'Africa Games',     TRUE, FALSE),
    ('roadmap',   'Roadmap',          TRUE, FALSE),
    ('website',   'Website creation', TRUE, FALSE)
ON CONFLICT (product_key) DO NOTHING;

-- CHECKS (run after):
--   select product_key, enabled, enforce from product_switches order by product_key;   -- 6 rows, all enabled
--   select tablename, rowsecurity from pg_tables where tablename = 'product_switches';  -- rowsecurity = true
--   select grantee, privilege_type from information_schema.role_table_grants
--     where table_name = 'product_switches';                                            -- service_role only
