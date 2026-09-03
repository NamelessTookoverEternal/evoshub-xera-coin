-- ============================================================================
-- EVOS Business Hub — "Website Creation" product
-- Tables: website_requests, website_chat_messages
-- Namespaced with the "website_" prefix so nothing collides with EVOSDATA's
-- or EvosGPT's tables in the shared Supabase project.
--
-- SECURITY MODEL (read this before touching RLS policies)
-- ----------------------------------------------------------------------------
-- Visitors never get a real login. Instead, when they open the chat we call
-- supabase.auth.signInAnonymously(), which gives the browser a real,
-- Supabase-issued auth.uid(). Every row a visitor creates is stamped with
-- that uid server-side (via `default auth.uid()`), and every RLS policy for
-- visitors checks `visitor_id = auth.uid()`. A visitor can never read or
-- write another visitor's row, because there is no query they can construct
-- that changes whose JWT they're holding.
--
-- Admins are real EVOSDATA Supabase accounts (shared auth). We do NOT trust
-- a client-supplied "isAdmin" flag anywhere. Instead we check membership in
-- the `admin_agents` table via a SECURITY DEFINER function, so the check
-- happens inside Postgres and can't be spoofed from the browser.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Admin roster (mirrors/extends EVOSDATA's admin accounts for this product)
-- ----------------------------------------------------------------------------
create table if not exists public.admin_agents (
  user_id     uuid primary key references auth.users(id) on delete cascade,
  display_name text not null default 'Agent',
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

alter table public.admin_agents enable row level security;

-- Only an existing active admin can see the roster; nobody can self-insert.
-- Managing this table is done from the Supabase dashboard / service_role only.
drop policy if exists "admin_agents_select_self_or_admin" on public.admin_agents;
create policy "admin_agents_select_self_or_admin"
  on public.admin_agents for select
  using (auth.uid() = user_id);

-- Helper function: SECURITY DEFINER so RLS policies on other tables can call
-- it without needing their own select-grant on admin_agents.
create or replace function public.is_website_admin()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select exists (
    select 1 from public.admin_agents
    where user_id = auth.uid() and is_active = true
  );
$$;

revoke all on function public.is_website_admin() from public;
grant execute on function public.is_website_admin() to authenticated, anon;

-- ----------------------------------------------------------------------------
-- 2. website_requests — the intake form
-- ----------------------------------------------------------------------------
create table if not exists public.website_requests (
  id            uuid primary key default gen_random_uuid(),
  visitor_id    uuid not null default auth.uid() references auth.users(id) on delete cascade,

  full_name     text not null check (char_length(full_name) between 1 and 120),
  email         text not null check (char_length(email) between 5 and 254),
  phone         text check (phone is null or char_length(phone) <= 30),
  business_name text check (business_name is null or char_length(business_name) <= 160),
  package       text not null check (package in ('starter','business','premium','custom')),
  budget_range  text check (budget_range is null or char_length(budget_range) <= 60),
  timeline      text check (timeline is null or char_length(timeline) <= 60),
  project_brief text not null check (char_length(project_brief) between 1 and 4000),

  status        text not null default 'new' check (status in ('new','in_review','in_chat','quoted','closed')),
  assigned_agent uuid references public.admin_agents(user_id),

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists idx_website_requests_visitor on public.website_requests(visitor_id);
create index if not exists idx_website_requests_status  on public.website_requests(status);

alter table public.website_requests enable row level security;

-- Visitors: can insert exactly one row per their own auth.uid(), and only
-- ever read/update rows that are theirs.
drop policy if exists "wr_visitor_insert_own" on public.website_requests;
create policy "wr_visitor_insert_own"
  on public.website_requests for insert
  with check (visitor_id = auth.uid());

drop policy if exists "wr_visitor_select_own" on public.website_requests;
create policy "wr_visitor_select_own"
  on public.website_requests for select
  using (visitor_id = auth.uid());

-- Admins: full read/update access, no delete (soft-close via status instead).
drop policy if exists "wr_admin_select_all" on public.website_requests;
create policy "wr_admin_select_all"
  on public.website_requests for select
  using (public.is_website_admin());

drop policy if exists "wr_admin_update_all" on public.website_requests;
create policy "wr_admin_update_all"
  on public.website_requests for update
  using (public.is_website_admin())
  with check (public.is_website_admin());

-- Keep updated_at fresh.
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_website_requests_touch on public.website_requests;
create trigger trg_website_requests_touch
  before update on public.website_requests
  for each row execute function public.touch_updated_at();

-- ----------------------------------------------------------------------------
-- 3. website_chat_messages — the live chat thread tied to a request
-- ----------------------------------------------------------------------------
create table if not exists public.website_chat_messages (
  id          uuid primary key default gen_random_uuid(),
  request_id  uuid not null references public.website_requests(id) on delete cascade,
  sender_id   uuid not null default auth.uid() references auth.users(id) on delete cascade,
  sender_role text not null check (sender_role in ('visitor','admin')),
  body        text not null check (char_length(body) between 1 and 2000),
  created_at  timestamptz not null default now()
);

create index if not exists idx_wcm_request   on public.website_chat_messages(request_id, created_at);
create index if not exists idx_wcm_sender    on public.website_chat_messages(sender_id);

alter table public.website_chat_messages enable row level security;

-- Visitor may read messages only on a request that is theirs.
drop policy if exists "wcm_visitor_select_own_thread" on public.website_chat_messages;
create policy "wcm_visitor_select_own_thread"
  on public.website_chat_messages for select
  using (
    exists (
      select 1 from public.website_requests r
      where r.id = request_id and r.visitor_id = auth.uid()
    )
  );

-- Visitor may insert a message only as themselves, tagged sender_role
-- 'visitor', and only into a thread that belongs to them.
drop policy if exists "wcm_visitor_insert_own_thread" on public.website_chat_messages;
create policy "wcm_visitor_insert_own_thread"
  on public.website_chat_messages for insert
  with check (
    sender_id = auth.uid()
    and sender_role = 'visitor'
    and exists (
      select 1 from public.website_requests r
      where r.id = request_id and r.visitor_id = auth.uid()
    )
  );

-- Admins may read/write any thread, but only tagged as 'admin' and stamped
-- with their own uid (so one admin can never impersonate another or the
-- visitor).
drop policy if exists "wcm_admin_select_all" on public.website_chat_messages;
create policy "wcm_admin_select_all"
  on public.website_chat_messages for select
  using (public.is_website_admin());

drop policy if exists "wcm_admin_insert_all" on public.website_chat_messages;
create policy "wcm_admin_insert_all"
  on public.website_chat_messages for insert
  with check (
    public.is_website_admin()
    and sender_id = auth.uid()
    and sender_role = 'admin'
  );

-- No update/delete policies for chat messages for anyone → messages are
-- append-only and immutable at the database level, which also means no
-- policy needs to guard against edits/deletes (default deny).

-- ----------------------------------------------------------------------------
-- 4. Realtime — only turn it on for these two tables, RLS still applies to
--    every realtime subscription automatically.
-- ----------------------------------------------------------------------------
alter publication supabase_realtime add table public.website_requests;
alter publication supabase_realtime add table public.website_chat_messages;

-- ----------------------------------------------------------------------------
-- 5. To make someone an admin/agent for this product, run (as service_role /
--    from the SQL editor, never from client code):
--    insert into public.admin_agents (user_id, display_name)
--    values ('<existing-evosdata-auth-user-uuid>', 'Agent Name');
-- ----------------------------------------------------------------------------
