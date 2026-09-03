-- ============================================================================
-- EVOS Business Hub — "Website Creation" hardening pass
-- Adds abuse/flood protection on top of 20260709_website_creation.sql.
-- Safe to run multiple times (idempotent: drops+recreates triggers/functions).
-- Does NOT touch existing RLS policies — those already default-deny anything
-- not explicitly allowed, this migration only adds extra checks *inside* the
-- already-allowed insert paths.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Cap how many intake requests a single visitor session can create.
--    Stops a bot from scripting signInAnonymously() + insert in a loop and
--    flooding the admin inbox. Real visitors never need more than a couple.
-- ----------------------------------------------------------------------------
create or replace function public.enforce_website_request_rate_limit()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  recent_count int;
begin
  select count(*) into recent_count
  from public.website_requests
  where visitor_id = new.visitor_id
    and created_at > now() - interval '1 hour';

  if recent_count >= 3 then
    raise exception 'rate_limit_exceeded: too many requests, please wait before submitting again'
      using errcode = 'P0001';
  end if;

  return new;
end;
$$;

drop trigger if exists trg_website_requests_rate_limit on public.website_requests;
create trigger trg_website_requests_rate_limit
  before insert on public.website_requests
  for each row execute function public.enforce_website_request_rate_limit();

-- ----------------------------------------------------------------------------
-- 2. Cap chat message throughput per sender (visitor or admin) to stop the
--    realtime channel being used to flood/DoS the thread.
-- ----------------------------------------------------------------------------
create or replace function public.enforce_chat_message_rate_limit()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  recent_count int;
begin
  select count(*) into recent_count
  from public.website_chat_messages
  where sender_id = new.sender_id
    and created_at > now() - interval '1 minute';

  if recent_count >= 20 then
    raise exception 'rate_limit_exceeded: sending messages too fast, please slow down'
      using errcode = 'P0001';
  end if;

  return new;
end;
$$;

drop trigger if exists trg_chat_messages_rate_limit on public.website_chat_messages;
create trigger trg_chat_messages_rate_limit
  before insert on public.website_chat_messages
  for each row execute function public.enforce_chat_message_rate_limit();

-- ----------------------------------------------------------------------------
-- 3. Belt-and-suspenders: strip anything that looks like raw HTML tags out of
--    the free-text fields at write time, in addition to the app always
--    escaping on render (escapeHtml in supabase-client.js). Defense in depth
--    in case a future client forgets to escape.
-- ----------------------------------------------------------------------------
create or replace function public.strip_tags(input text)
returns text
language sql
immutable
as $$
  select regexp_replace(coalesce(input, ''), '<[^>]*>', '', 'g');
$$;

create or replace function public.sanitize_website_request()
returns trigger
language plpgsql
as $$
begin
  new.full_name     := public.strip_tags(new.full_name);
  new.business_name := public.strip_tags(new.business_name);
  new.project_brief := public.strip_tags(new.project_brief);
  new.budget_range  := public.strip_tags(new.budget_range);
  new.timeline      := public.strip_tags(new.timeline);
  return new;
end;
$$;

drop trigger if exists trg_website_requests_sanitize on public.website_requests;
create trigger trg_website_requests_sanitize
  before insert or update on public.website_requests
  for each row execute function public.sanitize_website_request();

create or replace function public.sanitize_chat_message()
returns trigger
language plpgsql
as $$
begin
  new.body := public.strip_tags(new.body);
  if char_length(trim(new.body)) = 0 then
    raise exception 'empty_message: message body cannot be empty after sanitization'
      using errcode = 'P0001';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_chat_messages_sanitize on public.website_chat_messages;
create trigger trg_chat_messages_sanitize
  before insert on public.website_chat_messages
  for each row execute function public.sanitize_chat_message();
