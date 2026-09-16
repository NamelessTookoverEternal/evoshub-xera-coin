-- ============================================================
-- XERA Blockchain Integration V1 — additive schema
-- Section 9 of the brief. Nothing here alters existing mining
-- accounting semantics (xera_wallets, xera_transactions,
-- xera_mining_sessions, xera_allocations are untouched).
--
-- This migration adds:
--   1. xera_external_wallets   — verified BNB/TON wallet ownership
--   2. xera_wallet_link_nonces — short-lived nonces for wallet-link proofs
--   3. xera_onchain_claims     — indexing/confirmation of settled claims
--   4. xera_migration_snapshot — one-time frozen legacy balances + Merkle info
--   5. xera_chain_config       — deployed contract addresses per chain
--   6. RPCs enforcing atomic, cross-chain-aware claim reservation
-- ============================================================

-- ------------------------------------------------------------
-- 1. EXTERNAL WALLETS
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_external_wallets (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chain           TEXT NOT NULL CHECK (chain IN ('BNB', 'TON')),
    address         TEXT NOT NULL,
    is_primary      BOOLEAN NOT NULL DEFAULT true,
    verified_at     TIMESTAMPTZ,
    linked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    replaced_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'VERIFIED', 'REPLACED', 'REVOKED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- "One verified wallet per chain per user" (section 8 recommended policy) —
-- enforced as: at most one ACTIVE (VERIFIED, not yet replaced) row per
-- (user_id, chain). Replacing a wallet sets the old row's status to
-- REPLACED + replaced_at, which drops it out of this partial index,
-- before the new row can become VERIFIED.
CREATE UNIQUE INDEX IF NOT EXISTS xera_one_active_wallet_per_chain
    ON xera_external_wallets(user_id, chain)
    WHERE status = 'VERIFIED';

-- An address can only be claimed by one user per chain, ever, while active.
CREATE UNIQUE INDEX IF NOT EXISTS xera_wallet_address_unique_active
    ON xera_external_wallets(chain, address)
    WHERE status = 'VERIFIED';

CREATE INDEX IF NOT EXISTS idx_xera_ext_wallets_user ON xera_external_wallets(user_id);

-- Wallet-change cooldown (section 8, step 4). One row per (user_id, chain)
-- tracking the last successful wallet replacement, checked by the RPC below.
CREATE TABLE IF NOT EXISTS xera_wallet_cooldowns (
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chain           TEXT NOT NULL CHECK (chain IN ('BNB', 'TON')),
    last_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, chain)
);

-- ------------------------------------------------------------
-- 2. WALLET-LINK NONCES (BNB signature challenge / TON Connect proof)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_wallet_link_nonces (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chain       TEXT NOT NULL CHECK (chain IN ('BNB', 'TON')),
    address     TEXT NOT NULL,
    nonce       TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_xera_wallet_nonce_user ON xera_wallet_link_nonces(user_id);

-- ------------------------------------------------------------
-- 3. ON-CHAIN CLAIM INDEXING (section 9)
-- ------------------------------------------------------------

-- This table is confirmation/indexing data, never user-editable
-- accounting — the row is created the moment the backend RESERVES a
-- reference_id for a chain (before it even signs), and is updated only by
-- the confirmation/indexer step after independently validating the
-- on-chain transaction. See RPCs below.
CREATE TABLE IF NOT EXISTS xera_onchain_claims (
    id                  BIGSERIAL PRIMARY KEY,
    reference_id        TEXT NOT NULL,
    user_id             BIGINT NOT NULL REFERENCES users(id),
    chain               TEXT NOT NULL CHECK (chain IN ('BNB', 'TON')),
    wallet_address      TEXT NOT NULL,
    claimed_amount       NUMERIC(20,4) NOT NULL,
    transferable_amount  NUMERIC(20,4) NOT NULL,
    locked_amount        NUMERIC(20,4) NOT NULL,
    contract_address    TEXT,
    transaction_hash    TEXT,
    block_number        BIGINT,
    signed_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    signature_deadline  TIMESTAMPTZ NOT NULL,
    status              TEXT NOT NULL DEFAULT 'SIGNED' CHECK (status IN
                            ('SIGNED', 'SUBMITTED', 'CONFIRMED', 'FAILED', 'EXPIRED')),
    confirmed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT xera_onchain_split_matches CHECK (transferable_amount + locked_amount = claimed_amount)
);

-- THE cross-chain double-claim guarantee (section 17). A reference_id may
-- have at most one row in this table, full stop — the row is created at
-- RESERVATION time (before signing), so a reservation attempt for the same
-- reference_id on the other chain hits this unique constraint immediately,
-- not just at confirmation time.
CREATE UNIQUE INDEX IF NOT EXISTS xera_onchain_claim_reference_unique
    ON xera_onchain_claims(reference_id);

CREATE INDEX IF NOT EXISTS idx_xera_onchain_user ON xera_onchain_claims(user_id);
CREATE INDEX IF NOT EXISTS idx_xera_onchain_status ON xera_onchain_claims(status);
CREATE INDEX IF NOT EXISTS idx_xera_onchain_txhash ON xera_onchain_claims(transaction_hash);

-- ------------------------------------------------------------
-- 4. LEGACY MIGRATION SNAPSHOT (section 10)
-- ------------------------------------------------------------

-- Singleton describing the ONE frozen snapshot. No mechanism anywhere
-- inserts a second row with id=1 twice — the app-layer snapshot generator
-- reads this row first and refuses to run if one already exists.
CREATE TABLE IF NOT EXISTS xera_migration_snapshot_meta (
    id                      SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    cutoff_at               TIMESTAMPTZ,
    merkle_root             TEXT,
    total_snapshot_amount   NUMERIC(20,4),
    chain                   TEXT CHECK (chain IN ('BNB', 'TON')),
    contract_address        TEXT,
    generated_at            TIMESTAMPTZ,
    finalized               BOOLEAN NOT NULL DEFAULT false,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One frozen row per user, generated once at cutoff. leaf_index is what
-- gets fed into XeraMigrationClaim.claim() alongside the Merkle proof.
CREATE TABLE IF NOT EXISTS xera_migration_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    leaf_index      BIGINT NOT NULL UNIQUE,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    legacy_balance  NUMERIC(20,4) NOT NULL CHECK (legacy_balance > 0),
    claimed         BOOLEAN NOT NULL DEFAULT false,
    claimed_chain   TEXT CHECK (claimed_chain IN ('BNB', 'TON')),
    claimed_tx_hash TEXT,
    claimed_at      TIMESTAMPTZ,
    merkle_proof    JSONB,  -- array of 0x-prefixed sibling hashes, generated once by migration_snapshot/build_tree.py
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id) -- one legacy snapshot entry per user, ever
);

CREATE INDEX IF NOT EXISTS idx_xera_migration_user ON xera_migration_snapshot(user_id);

-- ------------------------------------------------------------
-- 5. DEPLOYED CONTRACT CONFIG (per chain)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xera_chain_config (
    chain                       TEXT PRIMARY KEY CHECK (chain IN ('BNB', 'TON')),
    network                     TEXT NOT NULL, -- 'testnet' | 'mainnet'
    xera_token_address          TEXT,
    xera_vesting_address        TEXT,
    xera_distributor_address    TEXT,
    xera_migration_address      TEXT,
    chain_supply_cap            NUMERIC(20,4), -- NULL until the BNB/TON split decision is made — see README
    onchain_enabled             BOOLEAN NOT NULL DEFAULT false,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO xera_chain_config (chain, network) VALUES ('BNB', 'testnet') ON CONFLICT (chain) DO NOTHING;
INSERT INTO xera_chain_config (chain, network) VALUES ('TON', 'testnet') ON CONFLICT (chain) DO NOTHING;

-- ============================================================
-- 6. ATOMIC OPERATIONS
-- ============================================================

-- ---- reserve a claim for exactly one chain (the cross-chain lock) -------
-- Called by the FastAPI claim-sign endpoint BEFORE it asks the ClaimSigner
-- to produce a signature. Creating this row IS the reservation — the
-- unique index on reference_id means a second call for the same
-- reference_id (same chain or the other one) fails here, atomically,
-- before any signature is ever produced for it.
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
    v_row xera_onchain_claims;
BEGIN
    IF p_chain NOT IN ('BNB', 'TON') THEN
        RAISE EXCEPTION 'invalid_chain' USING ERRCODE = 'P0101';
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

    RETURN v_row;
END;
$$;

-- ---- confirm a claim after independently validating the on-chain tx -----
CREATE OR REPLACE FUNCTION xera_confirm_onchain_claim(
    p_reference_id     TEXT,
    p_transaction_hash TEXT,
    p_block_number     BIGINT
) RETURNS xera_onchain_claims
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row xera_onchain_claims;
BEGIN
    SELECT * INTO v_row FROM xera_onchain_claims WHERE reference_id = p_reference_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'claim_not_found' USING ERRCODE = 'P0103';
    END IF;

    IF v_row.status = 'CONFIRMED' THEN
        RETURN v_row; -- idempotent: confirming twice with the same data is a no-op, not an error
    END IF;

    UPDATE xera_onchain_claims
        SET status = 'CONFIRMED',
            transaction_hash = p_transaction_hash,
            block_number = p_block_number,
            confirmed_at = now(),
            updated_at = now()
        WHERE reference_id = p_reference_id
        RETURNING * INTO v_row;

    RETURN v_row;
END;
$$;

-- ---- mark a reservation expired/failed, freeing nothing (reference_id
--      stays permanently consumed — a failed on-chain tx for a reserved
--      reference_id must NOT be retried on the other chain; the user
--      retries the SAME reservation/signature, or support intervenes) ----
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
        WHERE reference_id = p_reference_id AND status != 'CONFIRMED'
        RETURNING * INTO v_row;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'claim_not_found_or_already_confirmed' USING ERRCODE = 'P0104';
    END IF;

    RETURN v_row;
END;
$$;

-- ---- link/replace an external wallet, with cooldown enforcement ---------
CREATE OR REPLACE FUNCTION xera_link_external_wallet(
    p_user_id           BIGINT,
    p_chain             TEXT,
    p_address           TEXT,
    p_cooldown_seconds  INTEGER
) RETURNS xera_external_wallets
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_existing  xera_external_wallets;
    v_cooldown  xera_wallet_cooldowns;
    v_new       xera_external_wallets;
BEGIN
    IF p_chain NOT IN ('BNB', 'TON') THEN
        RAISE EXCEPTION 'invalid_chain' USING ERRCODE = 'P0101';
    END IF;

    SELECT * INTO v_cooldown FROM xera_wallet_cooldowns WHERE user_id = p_user_id AND chain = p_chain FOR UPDATE;
    IF FOUND AND v_cooldown.last_changed_at + make_interval(secs => p_cooldown_seconds) > now() THEN
        RAISE EXCEPTION 'wallet_change_cooldown_active' USING ERRCODE = 'P0105';
    END IF;

    -- Replace any existing VERIFIED wallet for this user+chain.
    SELECT * INTO v_existing
        FROM xera_external_wallets
        WHERE user_id = p_user_id AND chain = p_chain AND status = 'VERIFIED'
        FOR UPDATE;

    IF FOUND THEN
        UPDATE xera_external_wallets
            SET status = 'REPLACED', replaced_at = now(), updated_at = now()
            WHERE id = v_existing.id;
    END IF;

    BEGIN
        INSERT INTO xera_external_wallets (user_id, chain, address, is_primary, status, verified_at)
        VALUES (p_user_id, p_chain, p_address, true, 'VERIFIED', now())
        RETURNING * INTO v_new;
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'address_already_linked' USING ERRCODE = 'P0106';
    END;

    INSERT INTO xera_wallet_cooldowns (user_id, chain, last_changed_at)
    VALUES (p_user_id, p_chain, now())
    ON CONFLICT (user_id, chain) DO UPDATE SET last_changed_at = now();

    RETURN v_new;
END;
$$;

-- ---- claim a legacy snapshot balance exactly once ------------------------
CREATE OR REPLACE FUNCTION xera_claim_legacy_migration(
    p_user_id  BIGINT,
    p_chain    TEXT,
    p_tx_hash  TEXT
) RETURNS xera_migration_snapshot
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row xera_migration_snapshot;
BEGIN
    SELECT * INTO v_row FROM xera_migration_snapshot WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no_legacy_balance' USING ERRCODE = 'P0107';
    END IF;
    IF v_row.claimed THEN
        RAISE EXCEPTION 'already_claimed' USING ERRCODE = 'P0108';
    END IF;

    UPDATE xera_migration_snapshot
        SET claimed = true, claimed_chain = p_chain, claimed_tx_hash = p_tx_hash, claimed_at = now()
        WHERE user_id = p_user_id
        RETURNING * INTO v_row;

    RETURN v_row;
END;
$$;
