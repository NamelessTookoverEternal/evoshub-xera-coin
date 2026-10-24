-- ============================================================
-- XERA FIRST-TRANSFER READINESS — KYC status, one-time fee, notifications
--
-- SAFE TO RUN AS A NORMAL MIGRATION: it only ADDS tables, indexes and
-- functions. It does not touch balances, mining sessions, rewards, the
-- ledger, referrals, wallets or any existing row. Safe to re-run.
--
-- What this adds
--   1. xera_kyc                    one row per user: the CURRENT KYC status.
--                                  Only the backend (service_role) can write it.
--                                  Stores the minimum needed for a manual review;
--                                  NO identity-document images are stored here.
--   2. xera_fee_payments           one row per fee payment ATTEMPT, unique by the
--                                  payment reference. A partial unique index
--                                  guarantees at most ONE paid row per user.
--   3. xera_readiness_events       audit trail (who/what/when) for KYC + fee.
--   4. xera_notifications          server-written, per-user notifications.
--   5. xera_confirm_fee_payment()  idempotent: PENDING -> PAID only, once, only
--                                  when the verified amount + currency match.
--   6. xera_fail_fee_payment()     PENDING -> FAILED only (never touches PAID).
--
-- Nothing here lets a browser set a status: RLS is on and every privilege is
-- revoked from anon/authenticated. The API (service_role) is the only writer.
-- ============================================================

-- ------------------------------------------------------------
-- 1. KYC STATUS
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_kyc (
    user_id            BIGINT PRIMARY KEY REFERENCES users(id),
    status             TEXT NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING', 'VERIFIED', 'FAILED', 'MORE_INFO')),
    provider           TEXT NOT NULL DEFAULT 'MANUAL',   -- 'MANUAL' until a provider is configured
    provider_reference TEXT,                              -- the provider's applicant/session id, when one exists
    legal_name         TEXT,
    country            TEXT,
    id_type            TEXT,
    id_last4           TEXT,                              -- last 4 characters only, never the full number
    submitted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_by        BIGINT REFERENCES users(id),
    reviewed_at        TIMESTAMPTZ,
    review_note        TEXT,                              -- shown to the user on FAILED / MORE_INFO
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_xera_kyc_status ON xera_kyc (status, submitted_at);

-- ------------------------------------------------------------
-- 2. ONE-TIME FEE PAYMENTS
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_fee_payments (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    reference       TEXT NOT NULL UNIQUE,
    amount_minor    INTEGER NOT NULL CHECK (amount_minor > 0),   -- smallest unit (cents)
    currency        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PAID', 'FAILED')),
    provider        TEXT NOT NULL DEFAULT 'PAYSTACK',
    provider_tx_id  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at         TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_xera_fee_payments_user ON xera_fee_payments (user_id, created_at DESC);
-- The database itself refuses a second PAID row for the same user.
CREATE UNIQUE INDEX IF NOT EXISTS uq_xera_fee_one_paid_per_user
    ON xera_fee_payments (user_id) WHERE status = 'PAID';

-- ------------------------------------------------------------
-- 3. AUDIT TRAIL
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_readiness_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    actor_id    BIGINT,                      -- admin agent id, or NULL for system / the user themself
    event       TEXT NOT NULL,
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb,   -- never put secrets or document data here
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_xera_readiness_events_user ON xera_readiness_events (user_id, created_at DESC);

-- ------------------------------------------------------------
-- 4. NOTIFICATIONS (written by the server only, for real events only)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS xera_notifications (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    kind        TEXT NOT NULL,               -- e.g. KYC_VERIFIED, FEE_PAID
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_xera_notifications_user ON xera_notifications (user_id, created_at DESC);

-- ------------------------------------------------------------
-- 5. FEE CONFIRMATION (idempotent, amount + currency checked in the database)
-- ------------------------------------------------------------
-- Called by the backend ONLY after it has re-verified the transaction with the
-- payment provider. Returns the row. If the reference is unknown, already PAID
-- (duplicate webhook), or already FAILED, nothing changes and the current row
-- is returned, so a replayed webhook can never grant a second entitlement.
-- A verified amount/currency that does not match the attempt is REJECTED.
CREATE OR REPLACE FUNCTION xera_confirm_fee_payment(
    p_reference      TEXT,
    p_amount_minor   INTEGER,
    p_currency       TEXT,
    p_provider_tx_id TEXT
) RETURNS xera_fee_payments
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row xera_fee_payments;
BEGIN
    SELECT * INTO v_row FROM xera_fee_payments WHERE reference = p_reference FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'fee_payment_not_found' USING ERRCODE = 'P0401';
    END IF;

    IF v_row.status <> 'PENDING' THEN
        RETURN v_row;                                    -- duplicate / late event: no change
    END IF;

    IF v_row.amount_minor <> p_amount_minor OR upper(v_row.currency) <> upper(coalesce(p_currency, '')) THEN
        RAISE EXCEPTION 'fee_amount_mismatch' USING ERRCODE = 'P0402';
    END IF;

    UPDATE xera_fee_payments
       SET status = 'PAID', provider_tx_id = p_provider_tx_id, paid_at = now(), updated_at = now()
     WHERE id = v_row.id
     RETURNING * INTO v_row;

    INSERT INTO xera_readiness_events (user_id, actor_id, event, detail)
    VALUES (v_row.user_id, NULL, 'FEE_PAID', jsonb_build_object('reference', v_row.reference));

    RETURN v_row;
END;
$$;

CREATE OR REPLACE FUNCTION xera_fail_fee_payment(p_reference TEXT)
RETURNS xera_fee_payments
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row xera_fee_payments;
BEGIN
    UPDATE xera_fee_payments
       SET status = 'FAILED', updated_at = now()
     WHERE reference = p_reference AND status = 'PENDING'
     RETURNING * INTO v_row;
    IF NOT FOUND THEN
        SELECT * INTO v_row FROM xera_fee_payments WHERE reference = p_reference;
    ELSE
        INSERT INTO xera_readiness_events (user_id, actor_id, event, detail)
        VALUES (v_row.user_id, NULL, 'FEE_FAILED', jsonb_build_object('reference', v_row.reference));
    END IF;
    RETURN v_row;
END;
$$;

-- ------------------------------------------------------------
-- 6. PRIVILEGES — default deny; only the backend (service_role) touches these.
-- ------------------------------------------------------------
ALTER TABLE xera_kyc               ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_fee_payments      ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_readiness_events  ENABLE ROW LEVEL SECURITY;
ALTER TABLE xera_notifications     ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON xera_kyc, xera_fee_payments, xera_readiness_events, xera_notifications
    FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON xera_kyc, xera_fee_payments, xera_readiness_events, xera_notifications
    TO service_role;
GRANT USAGE, SELECT ON SEQUENCE xera_fee_payments_id_seq, xera_readiness_events_id_seq, xera_notifications_id_seq
    TO service_role;

REVOKE ALL ON FUNCTION xera_confirm_fee_payment(TEXT, INTEGER, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION xera_fail_fee_payment(TEXT)                         FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION xera_confirm_fee_payment(TEXT, INTEGER, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION xera_fail_fee_payment(TEXT)                         TO service_role;
