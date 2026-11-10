-- Allow the new 'whatsapp_bot' package on website requests.
-- Drops whatever check constraint currently limits website_requests.package, then recreates it.
do $$
declare c text;
begin
  for c in
    select conname from pg_constraint
    where conrelid = 'public.website_requests'::regclass and contype = 'c'
      and pg_get_constraintdef(oid) ilike '%package%'
  loop
    execute format('alter table public.website_requests drop constraint %I', c);
  end loop;
  alter table public.website_requests
    add constraint website_requests_package_check
    check (package in ('starter','business','premium','whatsapp_bot','custom'));
end $$;
