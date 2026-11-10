-- Website creation: repair for the "operator does not exist: bigint = uuid" (42883) chat error.
-- Safe to run more than once. Run it in the Supabase SQL editor.
--
-- Why: the live admin_agents table (shared with EVOS Data / DashXERA) uses BIGINT user ids, while
-- Supabase Auth ids (auth.uid()) are UUIDs. Any policy or function comparing the two directly fails with
-- 42883. This compares them as text, which works whatever the column types are.

-- 1. Columns the app already uses (the live database has them; this makes the repo match).
alter table public.website_chat_messages add column if not exists admin_user_id bigint;
alter table public.website_chat_messages alter column sender_id drop not null;

-- 2. Type-safe admin check.
create or replace function public.is_website_admin()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select exists (
    select 1 from public.admin_agents
    where user_id::text = auth.uid()::text and is_active = true
  );
$$;
revoke all on function public.is_website_admin() from public;
grant execute on function public.is_website_admin() to authenticated, anon;

-- 3. Type-safe visitor policies (the server uses the service role, so these only guard direct browser access).
drop policy if exists "wr_visitor_insert_own" on public.website_requests;
create policy "wr_visitor_insert_own" on public.website_requests for insert
  with check (visitor_id::text = auth.uid()::text);
drop policy if exists "wr_visitor_select_own" on public.website_requests;
create policy "wr_visitor_select_own" on public.website_requests for select
  using (visitor_id::text = auth.uid()::text);

drop policy if exists "wcm_visitor_select_own_thread" on public.website_chat_messages;
create policy "wcm_visitor_select_own_thread" on public.website_chat_messages for select
  using (exists (select 1 from public.website_requests r
                 where r.id::text = request_id::text and r.visitor_id::text = auth.uid()::text));
drop policy if exists "wcm_visitor_insert_own_thread" on public.website_chat_messages;
create policy "wcm_visitor_insert_own_thread" on public.website_chat_messages for insert
  with check (sender_id::text = auth.uid()::text and sender_role = 'visitor'
              and exists (select 1 from public.website_requests r
                          where r.id::text = request_id::text and r.visitor_id::text = auth.uid()::text));

-- 4. DIAGNOSTIC (read-only): if the chat still fails after this, send me the result of these two queries.
--   select table_name, column_name, data_type from information_schema.columns
--    where table_schema='public' and table_name in ('website_requests','website_chat_messages','admin_agents')
--      and column_name in ('id','request_id','sender_id','admin_user_id','visitor_id','user_id') order by 1,2;
--   select tgname, pg_get_triggerdef(oid) from pg_trigger
--    where tgrelid='public.website_chat_messages'::regclass and not tgisinternal;
