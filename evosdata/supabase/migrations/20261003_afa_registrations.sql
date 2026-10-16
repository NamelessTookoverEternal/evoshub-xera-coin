-- AFA (MTN SIM registration) service. Idempotent and additive.
create table if not exists public.afa_registrations (
    id                  bigserial primary key,
    user_id             bigint,
    agent_id            bigint,
    guest_email         text,
    full_name           text not null,
    phone_number        text not null,
    id_number           text not null,
    occupation          text,
    location            text,
    region              text,
    date_of_birth       date,
    price               numeric(10,2) not null,
    paystack_ref        text,
    evosdata_ref        text not null unique,
    status              text not null default 'pending_payment',
    sdl_registration_id text,
    provider_status     text,
    failure_reason      text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create index if not exists afa_reg_paystack_ref_idx on public.afa_registrations (paystack_ref);
create index if not exists afa_reg_phone_idx        on public.afa_registrations (phone_number);
create index if not exists afa_reg_agent_idx        on public.afa_registrations (agent_id);
create index if not exists afa_reg_sdl_idx          on public.afa_registrations (sdl_registration_id);
create index if not exists afa_reg_status_idx       on public.afa_registrations (status);
