-- ============================================================================
-- admin_agents — ecosystem-wide admin roster
--
-- This table already exists in the shared Supabase project: EVOSHUB created
-- it, and XERA (which ships inside evoshub as a separate module) reuses it
-- so one login works across all three products. This migration is
-- defensive, not a fresh creation — `if not exists` makes it a no-op
-- against the real database, which already has this table.
--
-- IMPORTANT — this is the LIVE shape (bigint), not the uuid draft that
-- appears in evoshub's earliest migration file. Admin agents authenticate
-- with their existing public.users username/password (bcrypt), the same
-- credentials used for customer and agent login — they never get a
-- separate Supabase Auth account, so user_id here is public.users.id
-- (bigint), never auth.users(id) (uuid). Every piece of code that actually
-- reads this table (evoshub's routes/admin.py, XERA's admin_auth.py, and
-- EVOSDATA's own admin_auth.py) agrees on bigint; treat that as the source
-- of truth over the older migration file.
-- ============================================================================

create table if not exists public.admin_agents (
    user_id      bigint primary key references public.users(id) on delete cascade,
    display_name text not null default 'Agent',
    is_active    boolean not null default true,
    created_at   timestamptz not null default now()
);

alter table public.admin_agents enable row level security;

-- Deliberately no policies. Only the service_role key (used server-side by
-- main.py) can read or write this table — becoming an admin isn't
-- self-service. Promote someone by running, as service_role:
--
--   insert into public.admin_agents (user_id, display_name)
--   values (<their public.users.id>, '<their name>');
--
-- Revoke access instantly (their next request gets 403, no need to wait
-- for their session token to expire) with:
--
--   update public.admin_agents set is_active = false where user_id = <id>;
