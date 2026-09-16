-- ============================================================
-- XERA Blockchain Hardening — global mining cap, claim retry safety,
-- and Supabase privilege/RLS hardening.
--
-- Additive/CREATE OR REPLACE only — nothing in 20260912_xera_blockchain_v1.sql
-- is dropped or renamed. Existing rows are preserved.
-- ============================================================

-- ------------------------------------------------------------
-- 1. CANONICAL CHAIN SUPPLY (Phase 2)
-- ------------------------------------------------------------
-- Mirrors blockchain/xera-economics.json — that file is the human-readable
-- source of truth; this is where the backend/frontend actually reads it
-- from at runtime. Keep both in sync by hand; there is no code that
-- generates one from the other.

UPDATE xera_chain_config SET chain_supply_cap = 400000000 WHERE chain = 'BNB' AND chain_supply_cap IS NULL;
UPDATE xera_chain_config SET chain_supply_cap = 100000000 WHERE chain = 'TON' AND chain_supply_cap IS NULL;

-- Fail closed if the two chain caps are ever set inconsistently with the
-- 500,000,000 total — this is a standing invariant, not a one-time check,
-- so it's a trigger rather than a migration-time assertion.
CREATE OR REPLACE FUNCTION xera_validate_chain_supply_total() RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_total NUMERIC;
    v_null_count INTEGER;
BEGIN
    SELECT count(*) FILTER (WHERE chain_supply_cap IS NULL), coalesce(sum(chain_supply_cap), 0)
        INTO v_null_count, v_total
        FROM xera_chain_config;

    IF v_null_count = 0 AND v_total != 500000000 THEN
        RAISE EXCEPTION 'chain_supply_caps_do_not_reconcile: BNB+TON=% (must equal 500000000)', v_total
            USING ERRCODE = 'P0110';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS xera_chain_config_validate_supply ON xera_chain_config;
CREATE TRIGGER xera_chain_config_validate_supply
    AFTER INSERT OR UPDATE OF chain_supply_cap ON xera_chain_config
    FOR EACH ROW EXECUTE FUNCTION xera_validate_chain_supply_total();

-- ------------------------------------------------------------
-- 2. GLOBAL MINING ALLOCATION — 75,000,000 ACROSS BOTH CHAINS (Phase 3)
-- ------------------------------------------------------------
-- This is the ACTUAL global cap. Each chain's smart-contract
-- `maxAllocation` is a separate, independent, per-chain safety ceiling —
-- it is NOT this cap and the two must never be confused (see
-- blockchain/xera-economics.json's mining._comment). Because BNB and TON
-- cannot observe each other's state, THIS table + the row lock below is
-- the only place the true global limit can be enforced.

CREATE TABLE IF NOT EXISTS xera_mining_allocation_state (
    id                      SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    global_reserved_amount  NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK (global_reserved_amount >= 0),
    global_cap              NUMERIC(20,4) NOT NULL DEFAULT 75000000,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO xera_mining_allocation_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- `global_reserved_amount` = sum of claimed_amount for every
-- xera_onchain_claims row currently in ('SIGNED','SUBMITTED','CONFIRMED').
-- It is incremented exactly once when a claim is first reserved, and
-- decremented exactly once if that specific claim later transitions to
-- FAILED/EXPIRED (freeing capacity for other claims — NOT the same
-- reference_id, which stays permanently consumed; see section 3).

CREATE OR REPLACE FUNCTION xera_reserve_onchain_claim(
    p_reference_id       TEXT,
    p_user_id            BIGINT,
    p_chain              TEXT,
    p_wallet_address      TEXT,
    p_claimed_amount      NUMERIC,
    p_transferable_amount NUMERIC,
    p_locked_amount       NUMERIC,
    p_contract_address    TEXT,
    p_deadline            TIMESTAMPTZ
) RETURNS xera_onchain_claims
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row   xera_onchain_claims;
    v_state xera_mining_allocation_state;
BEGIN
    IF p_chain NOT IN ('BNB', 'TON') THEN
        RAISE EXCEPTION 'invalid_chain' USING ERRCODE = 'P0101';
    END IF;
    IF p_claimed_amount <= 0 THEN
        RAISE EXCEPTION 'invalid_amount' USING ERRCODE = 'P0109';
    END IF;

    -- Lock the SINGLE global-allocation row first. Every concurrent
    -- reservation attempt — BNB or TON, any user — serializes on this one
    -- row lock, which is what makes "concurrent BNB + TON claims can never
    -- push the global total over 75,000,000" an actual guarantee rather
    -- than a best-effort SELECT-then-INSERT race.
    SELECT * INTO v_state FROM xera_mining_allocation_state WHERE id = 1 FOR UPDATE;

    IF v_state.global_reserved_amount + p_claimed_amount > v_state.global_cap THEN
        RAISE EXCEPTION 'global_mining_allocation_exceeded' USING ERRCODE = 'P0111';
    END IF;

    BEGIN
        INSERT INTO xera_onchain_claims (
            reference_id, user_id, chain, wallet_address,
            claimed_amount, transferable_amount, locked_amount,
            contract_address, signature_deadline, status
        ) VALUES (
            p_reference_id, p_user_id, p_chain, p_wallet_address,
            p_claimed_amount, p_transferable_amount, p_locked_amount,
            p_contract_address, p_deadline, 'SIGNED'
        )
        RETURNING * INTO v_row;
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'reference_already_reserved' USING ERRCODE = 'P0102';
    END;

    UPDATE xera_mining_allocation_state
        SET global_reserved_amount = global_reserved_amount + p_claimed_amount, updated_at = now()
        WHERE id = 1;

    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 3. CLAIM RETRY WITHOUT CROSS-CHAIN REPLAY (Phase 6)
-- ------------------------------------------------------------
-- `xera_onchain_claim_reference_unique` (from the base migration) is a
-- FULL unique index with no WHERE clause — once a reference_id row
-- exists, it can NEVER be inserted again, on either chain, in any status.
-- That is intentional and must not change (it's the actual cross-chain
-- guard). The consequence: a FAILED/EXPIRED claim cannot be "re-reserved"
-- via xera_reserve_onchain_claim — recovery MUST update the same existing
-- row. These two functions are that recovery path.

-- Sweep SIGNED claims whose signature deadline has passed without ever
-- being submitted/confirmed. Run this periodically (e.g. a cron/Edge
-- Function) — not called from the claim-sign/confirm request path itself.
CREATE OR REPLACE FUNCTION xera_expire_stale_onchain_claims() RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_expired_count INTEGER := 0;
    v_row RECORD;
BEGIN
    FOR v_row IN
        SELECT reference_id, claimed_amount FROM xera_onchain_claims
        WHERE status = 'SIGNED' AND signature_deadline < now()
        FOR UPDATE
    LOOP
        UPDATE xera_onchain_claims SET status = 'EXPIRED', updated_at = now()
            WHERE reference_id = v_row.reference_id;

        UPDATE xera_mining_allocation_state
            SET global_reserved_amount = greatest(0, global_reserved_amount - v_row.claimed_amount), updated_at = now()
            WHERE id = 1;

        v_expired_count := v_expired_count + 1;
    END LOOP;

    RETURN v_expired_count;
END;
$$;

-- Same free-the-global-slot treatment for explicit failures (tx reverted,
-- confirmation independently failed, etc). Only transitions SIGNED/SUBMITTED
-- -> FAILED exactly once — calling this on an already-FAILED/EXPIRED/
-- CONFIRMED row raises rather than silently double-releasing capacity.
CREATE OR REPLACE FUNCTION xera_mark_onchain_claim_failed(
    p_reference_id TEXT
) RETURNS xera_onchain_claims
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row xera_onchain_claims;
BEGIN
    UPDATE xera_onchain_claims
        SET status = 'FAILED', updated_at = now()
        WHERE reference_id = p_reference_id AND status IN ('SIGNED', 'SUBMITTED')
        RETURNING * INTO v_row;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'claim_not_found_or_not_failable' USING ERRCODE = 'P0104';
    END IF;

    UPDATE xera_mining_allocation_state
        SET global_reserved_amount = greatest(0, global_reserved_amount - v_row.claimed_amount), updated_at = now()
        WHERE id = 1;

    RETURN v_row;
END;
$$;

-- Recovery: re-activate a FAILED/EXPIRED claim (SAME reference_id, SAME
-- row — never a new one) so the user isn't permanently stranded. Chain
-- MAY differ from the original attempt (e.g. BNB tx failed for
-- gas/wallet reasons, user retries on TON) — this is still the one
-- settlement opportunity for this reference_id, just re-signed; it is
-- NOT a second claim, because it's an UPDATE of the one row the unique
-- index already locked in.
CREATE OR REPLACE FUNCTION xera_retry_onchain_claim(
    p_reference_id       TEXT,
    p_chain               TEXT,
    p_wallet_address      TEXT,
    p_contract_address    TEXT,
    p_deadline            TIMESTAMPTZ
) RETURNS xera_onchain_claims
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row   xera_onchain_claims;
    v_state xera_mining_allocation_state;
BEGIN
    IF p_chain NOT IN ('BNB', 'TON') THEN
        RAISE EXCEPTION 'invalid_chain' USING ERRCODE = 'P0101';
    END IF;

    SELECT * INTO v_row FROM xera_onchain_claims WHERE reference_id = p_reference_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'claim_not_found' USING ERRCODE = 'P0103';
    END IF;
    IF v_row.status NOT IN ('FAILED', 'EXPIRED') THEN
        RAISE EXCEPTION 'claim_not_retryable' USING ERRCODE = 'P0112';
    END IF;

    -- Global capacity may have been consumed by OTHER claims since this
    -- one failed — re-check and re-reserve under the same lock discipline
    -- as a fresh reservation.
    SELECT * INTO v_state FROM xera_mining_allocation_state WHERE id = 1 FOR UPDATE;
    IF v_state.global_reserved_amount + v_row.claimed_amount > v_state.global_cap THEN
        RAISE EXCEPTION 'global_mining_allocation_exceeded' USING ERRCODE = 'P0111';
    END IF;

    UPDATE xera_onchain_claims
        SET status = 'SIGNED', chain = p_chain, wallet_address = p_wallet_address,
            contract_address = p_contract_address, signature_deadline = p_deadline,
            transaction_hash = NULL, block_number = NULL, confirmed_at = NULL, updated_at = now()
        WHERE reference_id = p_reference_id
        RETURNING * INTO v_row;

    UPDATE xera_mining_allocation_state
        SET global_reserved_amount = global_reserved_amount + v_row.claimed_amount, updated_at = now()
        WHERE id = 1;

    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 4. SUPABASE PRIVILEGE / RLS HARDENING (Phase 7)
-- ------------------------------------------------------------
-- Privilege model: this app does NOT use Supabase Auth (auth.uid()) — it
-- has its own HMAC-signed session tokens verified in the FastAPI backend
-- (see python/xera/user_auth.py). That means Postgres/PostgREST has no
-- reliable way to know "which app-user is this request" on its own, so
-- row-level policies keyed on auth.uid() would be meaningless here (there
-- is no Supabase-authenticated JWT for these requests in the first place).
--
-- The correct — and only honest — security boundary given that
-- constraint is: DENY anon/authenticated entirely at the database level
-- for every new XERA blockchain table and function, and rely exclusively
-- on the FastAPI backend (using the service_role key, which bypasses RLS
-- by design in Supabase) to enforce per-user authorization in application
-- code. That authorization already exists (claims.py / migration.py /
-- wallet_link.py all check p_user_id against the authenticated session's
-- own user_id before ever calling these RPCs) — this section's job is
-- only to make sure nothing can reach these tables/functions AROUND that
-- application code via a leaked anon/authenticated key and PostgREST.
--
-- If a future migration adds real Supabase Auth to this app, these
-- default-deny policies should be replaced with real per-user policies
-- keyed on auth.uid() — until then, default-deny is the correct model,
-- not a placeholder.

ALTER TABLE xera_external_wallets        ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_wallet_link_nonces           ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_wallet_cooldowns        ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_onchain_claims          ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_migration_snapshot_meta ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_migration_snapshot      ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_chain_config            ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_mining_allocation_state ENABLE ROW LEVEL SECURITY;

-- No policies are created for anon/authenticated on any of the above —
-- RLS with zero policies means zero rows are visible/writable to any role
-- that isn't exempted from RLS. `service_role` has BYPASSRLS by default in
-- Supabase, so the FastAPI backend (which authenticates with
-- SUPABASE_SERVICE_ROLE_KEY exclusively for all XERA blockchain access —
-- see python/xera/chain/config.py) is unaffected by any policy here.

REVOKE ALL ON xera_external_wallets        FROM PUBLIC;
REVOKE ALL ON xera_wallet_link_nonces           FROM PUBLIC;
REVOKE ALL ON xera_wallet_cooldowns        FROM PUBLIC;
REVOKE ALL ON xera_onchain_claims          FROM PUBLIC;
REVOKE ALL ON xera_migration_snapshot_meta FROM PUBLIC;
REVOKE ALL ON xera_migration_snapshot      FROM PUBLIC;
REVOKE ALL ON xera_chain_config            FROM PUBLIC;
REVOKE ALL ON xera_mining_allocation_state FROM PUBLIC;

-- SECURITY DEFINER functions are independently executable via PostgREST's
-- RPC endpoint regardless of table grants — REVOKE EXECUTE explicitly, or
-- an anon-key holder could call e.g. xera_link_external_wallet(<victim's
-- user_id>, ...) directly and bypass every check in wallet_link.py.
REVOKE EXECUTE ON FUNCTION xera_reserve_onchain_claim(TEXT, BIGINT, TEXT, TEXT, NUMERIC, NUMERIC, NUMERIC, TEXT, TIMESTAMPTZ) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_confirm_onchain_claim(TEXT, TEXT, BIGINT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_mark_onchain_claim_failed(TEXT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_retry_onchain_claim(TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_expire_stale_onchain_claims() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_link_external_wallet(BIGINT, TEXT, TEXT, INTEGER) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_claim_legacy_migration(BIGINT, TEXT, TEXT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION xera_validate_chain_supply_total() FROM PUBLIC;

-- service_role bypasses RLS and typically already has EXECUTE via its
-- superuser-like grants in Supabase, but grant explicitly rather than
-- relying on that default, so this migration is self-contained and
-- correct even if a project's default role grants ever change.
GRANT EXECUTE ON FUNCTION xera_reserve_onchain_claim(TEXT, BIGINT, TEXT, TEXT, NUMERIC, NUMERIC, NUMERIC, TEXT, TIMESTAMPTZ) TO service_role;
GRANT EXECUTE ON FUNCTION xera_confirm_onchain_claim(TEXT, TEXT, BIGINT) TO service_role;
GRANT EXECUTE ON FUNCTION xera_mark_onchain_claim_failed(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION xera_retry_onchain_claim(TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ) TO service_role;
GRANT EXECUTE ON FUNCTION xera_expire_stale_onchain_claims() TO service_role;
GRANT EXECUTE ON FUNCTION xera_link_external_wallet(BIGINT, TEXT, TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION xera_claim_legacy_migration(BIGINT, TEXT, TEXT) TO service_role;
GRANT ALL ON xera_external_wallets, xera_wallet_link_nonces, xera_wallet_cooldowns,
    xera_onchain_claims, xera_migration_snapshot_meta, xera_migration_snapshot,
    xera_chain_config, xera_mining_allocation_state TO service_role;

-- ------------------------------------------------------------
-- 5. ATOMIC NONCE CONSUMPTION (Phase 8)
-- ------------------------------------------------------------
-- The original consume_nonce in python/xera/chain/nonces.py did a
-- SELECT-then-UPDATE, which is a TOCTOU race: two concurrent requests
-- presenting the SAME nonce could both pass the SELECT before either
-- wrote consumed_at, letting one captured nonce+signature pair be
-- replayed. This function makes consumption a single atomic conditional
-- UPDATE — `consumed_at IS NULL` is evaluated and written in one
-- statement, so exactly one concurrent caller can ever win.
--
-- Every binding check (user, chain, address, expiry) is INSIDE the same
-- UPDATE's WHERE clause, so a nonce issued to one user/chain/address can
-- never be consumed for a different one, even under concurrency.
CREATE OR REPLACE FUNCTION xera_consume_wallet_nonce(
    p_user_id  BIGINT,
    p_chain    TEXT,
    p_address  TEXT,
    p_nonce    TEXT
) RETURNS xera_wallet_link_nonces
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row      xera_wallet_link_nonces;
    v_existing xera_wallet_link_nonces;
BEGIN
    UPDATE xera_wallet_link_nonces
        SET consumed_at = now()
        WHERE nonce = p_nonce
          AND user_id = p_user_id
          AND chain = p_chain
          AND lower(address) = lower(p_address)
          AND consumed_at IS NULL
          AND expires_at > now()
        RETURNING * INTO v_row;

    IF FOUND THEN
        RETURN v_row;
    END IF;

    -- Nothing was consumed — work out WHY, so the caller can return a
    -- precise error instead of a generic failure. These reads are
    -- deliberately AFTER the atomic update attempt: they're only for
    -- error reporting and can never grant access.
    SELECT * INTO v_existing FROM xera_wallet_link_nonces WHERE nonce = p_nonce LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'nonce_not_found' USING ERRCODE = 'P0120';
    END IF;
    IF v_existing.consumed_at IS NOT NULL THEN
        RAISE EXCEPTION 'nonce_already_consumed' USING ERRCODE = 'P0121';
    END IF;
    IF v_existing.expires_at <= now() THEN
        RAISE EXCEPTION 'nonce_expired' USING ERRCODE = 'P0122';
    END IF;
    IF v_existing.user_id != p_user_id OR v_existing.chain != p_chain THEN
        RAISE EXCEPTION 'nonce_not_found' USING ERRCODE = 'P0120'; -- deliberately vague: don't confirm another user's nonce exists
    END IF;
    IF lower(v_existing.address) != lower(p_address) THEN
        RAISE EXCEPTION 'nonce_address_mismatch' USING ERRCODE = 'P0123';
    END IF;

    RAISE EXCEPTION 'nonce_not_found' USING ERRCODE = 'P0120';
END;
$$;

REVOKE EXECUTE ON FUNCTION xera_consume_wallet_nonce(BIGINT, TEXT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION xera_consume_wallet_nonce(BIGINT, TEXT, TEXT, TEXT) TO service_role;
