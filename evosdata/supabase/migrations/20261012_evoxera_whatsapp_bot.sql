-- Evoxera WhatsApp bot. Idempotent and additive: nothing existing is altered.

-- 1) Tag and track WhatsApp orders on the existing orders table.
alter table public.orders add column if not exists source     text;
alter table public.orders add column if not exists wa_number  text;
alter table public.orders add column if not exists wa_notify  text;  -- null | unpaid | paid | done

create index if not exists orders_wa_source_idx
    on public.orders (source, wa_notify) where source = 'whatsapp';
create index if not exists orders_wa_number_idx
    on public.orders (wa_number) where wa_number is not null;

-- 2) Conversation state, so a restart or redeploy never loses a customer mid-order.
create table if not exists public.wa_sessions (
    wa_number  text primary key,
    state      text not null default 'idle',
    data       jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

-- 3) Remembers which customer each owner alert was about, so the owner can
--    swipe-reply to an alert and have it relayed to that customer.
create table if not exists public.wa_alerts (
    msg_id     text primary key,
    customer   text not null,
    created_at timestamptz not null default now()
);
create index if not exists wa_alerts_created_idx on public.wa_alerts (created_at);
