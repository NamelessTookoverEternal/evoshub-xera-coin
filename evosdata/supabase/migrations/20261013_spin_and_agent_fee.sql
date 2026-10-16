-- Spin to Win + Become-Agent fee. Idempotent and additive: nothing existing is altered
-- except one optional `source` column on orders (already added by the WhatsApp bot migration).

alter table public.orders add column if not exists source text;   -- 'whatsapp' | 'spin' | null (website)

-- ---------------------------------------------------------------------------
-- 1) SPINS: one row per user per UTC day (the unique constraint IS the daily limit)
-- ---------------------------------------------------------------------------
create table if not exists public.spins (
    id            bigserial primary key,
    user_id       bigint      not null references public.users(id) on delete cascade,
    spin_date     date        not null,                 -- UTC day; resets at 00:00 UTC (= midnight in Ghana)
    prize_gb      integer,                              -- null = "Try again"
    boosted       boolean     not null default false,   -- a qualifying 3GB+ purchase was applied (never shown to the user)
    boost_order_id bigint,                              -- the purchase that was consumed for the boost
    status        text        not null default 'lost',  -- lost | won | claimed | expired
    claim_phone   text,
    claim_network text,
    order_id      bigint,                               -- the reward order created at claim time
    created_at    timestamptz not null default now(),
    claimed_at    timestamptz,
    constraint spins_one_per_user_per_day unique (user_id, spin_date)
);
create index if not exists spins_date_idx   on public.spins (spin_date);
create index if not exists spins_user_idx   on public.spins (user_id, created_at desc);

-- A purchase can boost only one spin, ever.
create table if not exists public.spin_boost_orders (
    order_id   bigint primary key,
    user_id    bigint      not null,
    spin_id    bigint      references public.spins(id) on delete set null,
    created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 2) AGENT FEE PAYMENTS
-- ---------------------------------------------------------------------------
create table if not exists public.agent_fee_payments (
    id              bigserial primary key,
    user_id         bigint      not null references public.users(id) on delete cascade,
    reference       text        not null unique,        -- EVOS-AGTFEE-...
    amount          numeric(10,2) not null,             -- set by the server, never by the browser
    status          text        not null default 'pending',  -- pending | paid | activated | failed | expired
    paid_at         timestamptz,                        -- when Paystack says it was paid
    activate_after  timestamptz,                        -- paid_at + 30 minutes
    activated_at    timestamptz,
    last_checked_at timestamptz,
    created_at      timestamptz not null default now()
);
create index if not exists agent_fee_user_idx   on public.agent_fee_payments (user_id, created_at desc);
create index if not exists agent_fee_status_idx on public.agent_fee_payments (status) where status in ('pending','paid');
