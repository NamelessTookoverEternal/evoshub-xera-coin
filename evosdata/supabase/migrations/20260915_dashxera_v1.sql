-- ============================================================================
-- DASHXERA v1 — admin operations dashboard for EVOSDATA
-- Run once in the EVOSDATA Supabase SQL editor. Safe to re-run.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. provider_incidents
--    Today, when DataMart rejects a purchase because the wallet is empty, the
--    only trace is a logger.error() line that scrolls off Render's log tail.
--    This table is the durable version of that line, deduplicated so one bad
--    hour doesn't become 400 rows.
-- ----------------------------------------------------------------------------
create table if not exists public.provider_incidents (
    id            bigserial primary key,

    provider      text not null,                 -- DATAMART / BUNDLES_GHANA / SWIFT_DATA_LINK / AGYEKUMDATA / PAYSTACK
    kind          text not null,                 -- low_balance / rate_limited / provider_down / out_of_stock / auth / purchase_failed
    severity      text not null default 'warning' check (severity in ('critical','warning','info')),

    message       text not null,                 -- raw-ish text, trimmed
    fingerprint   text not null,                 -- provider + kind + normalised message

    order_id      bigint,
    reference     text,
    network       text,
    bundle        text,

    occurrences   integer not null default 1,
    first_seen_at timestamptz not null default now(),
    last_seen_at  timestamptz not null default now(),

    resolved_at   timestamptz,
    resolved_by   text,
    note          text
);

create index if not exists idx_provider_incidents_seen
    on public.provider_incidents (last_seen_at desc);
create index if not exists idx_provider_incidents_open
    on public.provider_incidents (resolved_at, severity, last_seen_at desc);
create unique index if not exists uniq_provider_incidents_fingerprint_open
    on public.provider_incidents (fingerprint)
    where resolved_at is null;

alter table public.provider_incidents enable row level security;
-- No policies: the service-role key used by the FastAPI backend bypasses RLS,
-- and nothing else should ever read this table directly.

-- ----------------------------------------------------------------------------
-- 2. dashxera_actions — audit trail for anything an admin triggers from the
--    dashboard. Reprocessing a paid order moves real money, so it gets a row.
-- ----------------------------------------------------------------------------
create table if not exists public.dashxera_actions (
    id          bigserial primary key,
    action      text not null,                   -- reprocess / resolve_incident / ...
    order_id    bigint,
    reference   text,
    provider    text,
    outcome     text not null,                   -- success / failed / skipped
    detail      text,
    actor       text,                            -- label the admin sent, if any
    created_at  timestamptz not null default now()
);

create index if not exists idx_dashxera_actions_created
    on public.dashxera_actions (created_at desc);
create index if not exists idx_dashxera_actions_order
    on public.dashxera_actions (order_id);

alter table public.dashxera_actions enable row level security;

-- ----------------------------------------------------------------------------
-- 3. orders — columns the reprocess flow writes back
-- ----------------------------------------------------------------------------
alter table public.orders add column if not exists reprocessed_at    timestamptz;
alter table public.orders add column if not exists reprocess_count   integer default 0;
alter table public.orders add column if not exists last_error        text;

-- ----------------------------------------------------------------------------
-- 4. Indexes the dashboard's date-range queries lean on. Without these, a
--    90-day summary sequential-scans the whole orders table on every refresh.
-- ----------------------------------------------------------------------------
create index if not exists idx_orders_created_at
    on public.orders (created_at desc);
create index if not exists idx_orders_status_created
    on public.orders (status, created_at desc);

-- The stranded-order query: paid, but never handed to a provider.
create index if not exists idx_orders_stranded
    on public.orders (created_at desc)
    where datamart_ref is null;
