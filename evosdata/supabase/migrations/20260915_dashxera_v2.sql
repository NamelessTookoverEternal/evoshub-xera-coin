-- ============================================================================
-- DASHXERA v2 — hardening pass
-- Run AFTER 20260915_dashxera_v1.sql. Safe to re-run. Purely additive:
-- no column is dropped, no existing value is rewritten.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Order columns DashXera writes back.
--    dispatch_provider is new: orders currently record provider_priority (a
--    tier index) but never the provider name, so "which provider handled
--    this?" can only be inferred for historical rows. From here on the
--    reprocess path records it outright.
-- ----------------------------------------------------------------------------
alter table public.orders add column if not exists reprocessed_at    timestamptz;
alter table public.orders add column if not exists reprocess_count   integer default 0;
alter table public.orders add column if not exists last_error        text;
alter table public.orders add column if not exists dispatch_provider text;

-- base_price already exists (agent store checkouts write it). Nothing here
-- backfills it — an order's historical cost is whatever was recorded at the
-- time, and a blank stays blank rather than inheriting today's price.

-- ----------------------------------------------------------------------------
-- 2. Audit trail — richer than v1. Keeps the old rows intact.
-- ----------------------------------------------------------------------------
create table if not exists public.dashxera_actions (
    id          bigserial primary key,
    action      text not null,
    order_id    bigint,
    reference   text,
    provider    text,
    outcome     text not null,
    detail      text,
    actor       text,
    created_at  timestamptz not null default now()
);

alter table public.dashxera_actions add column if not exists previous_status text;
alter table public.dashxera_actions add column if not exists new_status      text;
alter table public.dashxera_actions add column if not exists provider_ref    text;

create index if not exists idx_dashxera_actions_created on public.dashxera_actions (created_at desc);
create index if not exists idx_dashxera_actions_order   on public.dashxera_actions (order_id);
alter table public.dashxera_actions enable row level security;

-- ----------------------------------------------------------------------------
-- 3. Incidents — v1 table, plus columns the provider health panel reads.
-- ----------------------------------------------------------------------------
create table if not exists public.provider_incidents (
    id            bigserial primary key,
    provider      text not null,
    kind          text not null,
    severity      text not null default 'warning' check (severity in ('critical','warning','info')),
    message       text not null,
    fingerprint   text not null,
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
create index if not exists idx_provider_incidents_provider
    on public.provider_incidents (provider, last_seen_at desc);
create unique index if not exists uniq_provider_incidents_fingerprint_open
    on public.provider_incidents (fingerprint) where resolved_at is null;

alter table public.provider_incidents enable row level security;

-- ----------------------------------------------------------------------------
-- 4. Indexes for the reporting windows.
-- ----------------------------------------------------------------------------
create index if not exists idx_orders_created_at     on public.orders (created_at desc);
create index if not exists idx_orders_status_created on public.orders (status, created_at desc);
create index if not exists idx_orders_agent_created  on public.orders (agent_id, created_at desc)
    where agent_id is not null;
create index if not exists idx_orders_stranded       on public.orders (created_at desc)
    where datamart_ref is null;

-- ----------------------------------------------------------------------------
-- 5. Aggregation in the database rather than in Python.
--
--    Without this, a 90-day summary pulls every order row over the wire and
--    sums them in the API process. This does it in one query.
--
--    The three money columns are deliberately separate:
--      sold        = orders.price       — what the customer was charged
--      base_cost   = orders.base_price  — historical cost, recorded on the row
--      agent_sold  = orders.price where the order came through an agent
--
--    base_cost counts ONLY rows that carry their own base_price. Orders
--    without one are counted in orders_missing_base so the dashboard can say
--    how much of the margin figure is actually grounded.
-- ----------------------------------------------------------------------------
create or replace function public.dashxera_order_summary(since_ts timestamptz)
returns table (
    total_orders          bigint,
    awaiting_payment      bigint,
    processing_orders     bigint,
    successful_orders     bigint,
    failed_orders         bigint,
    other_orders          bigint,
    paid_orders           bigint,
    sold                  numeric,
    base_cost             numeric,
    orders_with_base      bigint,
    orders_missing_base   bigint,
    sold_missing_base     numeric,
    failed_value          numeric,
    undispatched_orders   bigint,
    undispatched_value    numeric,
    agent_orders          bigint,
    agent_sold            numeric,
    agent_price_total     numeric,
    direct_orders         bigint,
    direct_sold           numeric
)
language sql
stable
security definer
set search_path = public
as $$
    with scoped as (
        select
            o.*,
            (o.status <> 'pending_payment')                       as collected,
            (o.base_price is not null)                            as has_base,
            (o.agent_id is not null)                              as is_agent
        from public.orders o
        where o.created_at >= since_ts
    )
    select
        count(*),
        count(*) filter (where status = 'pending_payment'),
        count(*) filter (where status in ('paid','processing')),
        count(*) filter (where status = 'successful'),
        count(*) filter (where status = 'failed'),
        count(*) filter (where status not in
            ('pending_payment','paid','processing','successful','failed')),
        count(*) filter (where collected),

        coalesce(sum(price)      filter (where collected), 0),
        coalesce(sum(base_price) filter (where collected and has_base), 0),
        count(*)                 filter (where collected and has_base),
        count(*)                 filter (where collected and not has_base),
        coalesce(sum(price)      filter (where collected and not has_base), 0),

        coalesce(sum(price) filter (where status = 'failed'), 0),

        count(*)            filter (where collected and datamart_ref is null and status <> 'successful'),
        coalesce(sum(price) filter (where collected and datamart_ref is null and status <> 'successful'), 0),

        count(*)                  filter (where collected and is_agent),
        coalesce(sum(price),       0) filter (where collected and is_agent),
        coalesce(sum(agent_price), 0) filter (where collected and is_agent),
        count(*)                  filter (where collected and not is_agent),
        coalesce(sum(price),       0) filter (where collected and not is_agent)
    from scoped;
$$;

revoke all on function public.dashxera_order_summary(timestamptz) from public, anon, authenticated;

-- ----------------------------------------------------------------------------
-- 6. Daily series for the chart — same rules, bucketed by day.
-- ----------------------------------------------------------------------------
create or replace function public.dashxera_daily_series(since_ts timestamptz)
returns table (
    day        date,
    orders     bigint,
    sold       numeric,
    base_cost  numeric,
    failed     bigint
)
language sql
stable
security definer
set search_path = public
as $$
    select
        date_trunc('day', o.created_at)::date,
        count(*) filter (where o.status <> 'pending_payment'),
        coalesce(sum(o.price)      filter (where o.status <> 'pending_payment'), 0),
        coalesce(sum(o.base_price) filter (where o.status <> 'pending_payment'
                                             and o.base_price is not null), 0),
        count(*) filter (where o.status = 'failed')
    from public.orders o
    where o.created_at >= since_ts
    group by 1
    order by 1;
$$;

revoke all on function public.dashxera_daily_series(timestamptz) from public, anon, authenticated;

-- ----------------------------------------------------------------------------
-- 7. Per-agent rollup. agent_id references users(id); there is no separate
--    agents table, so the display name comes from users.
-- ----------------------------------------------------------------------------
create or replace function public.dashxera_agent_summary(since_ts timestamptz)
returns table (
    agent_id          bigint,
    agent_name        text,
    agent_username    text,
    orders            bigint,
    sold              numeric,
    agent_price_total numeric,
    base_cost         numeric,
    orders_with_base  bigint,
    successful_orders bigint,
    failed_orders     bigint
)
language sql
stable
security definer
set search_path = public
as $$
    select
        o.agent_id,
        coalesce(nullif(u.store_name, ''), nullif(u.full_name, ''), u.username, 'Agent ' || o.agent_id),
        u.username,
        count(*),
        coalesce(sum(o.price), 0),
        coalesce(sum(o.agent_price), 0),
        coalesce(sum(o.base_price) filter (where o.base_price is not null), 0),
        count(*) filter (where o.base_price is not null),
        count(*) filter (where o.status = 'successful'),
        count(*) filter (where o.status = 'failed')
    from public.orders o
    left join public.users u on u.id = o.agent_id
    where o.created_at >= since_ts
      and o.agent_id is not null
      and o.status <> 'pending_payment'
    group by o.agent_id, u.store_name, u.full_name, u.username
    order by 5 desc;
$$;

revoke all on function public.dashxera_agent_summary(timestamptz) from public, anon, authenticated;

-- ----------------------------------------------------------------------------
-- 8. Provider activity, derived from real order outcomes rather than a
--    balance endpoint nobody publishes. Historical rows have no
--    dispatch_provider, so they group under 'UNRECORDED' — honest about what
--    we actually know.
-- ----------------------------------------------------------------------------
create or replace function public.dashxera_provider_activity(since_ts timestamptz)
returns table (
    provider          text,
    orders            bigint,
    successful_orders bigint,
    failed_orders     bigint,
    last_success_at   timestamptz
)
language sql
stable
security definer
set search_path = public
as $$
    select
        coalesce(nullif(o.dispatch_provider, ''), 'UNRECORDED'),
        count(*),
        count(*) filter (where o.status = 'successful'),
        count(*) filter (where o.status = 'failed'),
        max(o.created_at) filter (where o.status = 'successful')
    from public.orders o
    where o.created_at >= since_ts
      and o.status <> 'pending_payment'
    group by 1
    order by 2 desc;
$$;

revoke all on function public.dashxera_provider_activity(timestamptz) from public, anon, authenticated;
