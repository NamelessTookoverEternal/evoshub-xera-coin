-- DataMart wallet tracking for automatic out-of-stock.
-- Idempotent and purely additive. Run in the EVOSDATA Supabase SQL editor.

create table if not exists public.datamart_wallet (
    id               integer primary key check (id = 1),
    balance          numeric(12,2),
    previous_balance numeric(12,2),
    last_checked_at  timestamptz,
    last_ok_at       timestamptz,
    last_changed_at  timestamptz,
    last_error       text
);

create table if not exists public.datamart_wallet_log (
    id               bigserial primary key,
    balance          numeric(12,2) not null,
    previous_balance numeric(12,2),
    delta            numeric(12,2),
    source           text not null default 'poller',
    created_at       timestamptz not null default now()
);

create index if not exists datamart_wallet_log_created_idx
    on public.datamart_wallet_log (created_at desc);

-- Backend uses the service_role key; keep the tables closed to the public API.
alter table public.datamart_wallet enable row level security;
alter table public.datamart_wallet_log enable row level security;
