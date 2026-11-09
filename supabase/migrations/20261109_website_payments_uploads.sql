-- ============================================================================
-- Website Creation: payments, receipts and customer file uploads
--
-- Adds to website_requests: the price the customer was quoted, how they chose to
-- proceed (pay now / talk first), payment state (Paystack or USDT crypto), the
-- XERA saving and the receipt number.
-- Adds website_request_files + a private storage bucket for logos, designs, docs.
--
-- SECURITY: every payment column is written ONLY by the backend (service_role).
-- Visitors keep their old right to insert a request, but only the intake columns
-- (column-level grant below), so nobody can insert a row that already says "paid".
-- Safe to re-run.
-- ============================================================================

alter table public.website_requests
  add column if not exists contact_path       text   check (contact_path in ('pay_now','talk')),
  add column if not exists list_price_ghs     numeric(12,2),
  add column if not exists price_ghs          numeric(12,2),
  add column if not exists xera_discount_ghs  numeric(12,2) not null default 0,
  add column if not exists amount_due_ghs     numeric(12,2),
  add column if not exists payment_status     text   not null default 'unpaid'
                                              check (payment_status in ('unpaid','pending','paid','failed')),
  add column if not exists payment_method     text   check (payment_method in ('paystack','crypto')),
  add column if not exists payment_reference  text,
  add column if not exists crypto_usd_cents   integer,
  add column if not exists paid_at            timestamptz,
  add column if not exists receipt_no         text;

create unique index if not exists uq_website_requests_payment_reference
  on public.website_requests(payment_reference) where payment_reference is not null;
create unique index if not exists uq_website_requests_receipt_no
  on public.website_requests(receipt_no) where receipt_no is not null;
create index if not exists idx_website_requests_payment_status
  on public.website_requests(payment_status);

-- Visitors may insert only the intake columns (never payment columns).
revoke insert on public.website_requests from anon, authenticated;
grant insert (visitor_id, full_name, email, phone, business_name, package,
              budget_range, timeline, project_brief)
  on public.website_requests to authenticated;

-- ----------------------------------------------------------------------------
-- Uploaded files (logos, designs, documents). Backend-only table: RLS on, no
-- policies, so only service_role can touch it.
-- ----------------------------------------------------------------------------
create table if not exists public.website_request_files (
  id            uuid primary key default gen_random_uuid(),
  request_id    uuid not null references public.website_requests(id) on delete cascade,
  storage_path  text not null unique,
  file_name     text not null check (char_length(file_name) between 1 and 200),
  mime_type     text not null,
  size_bytes    integer not null check (size_bytes > 0),
  created_at    timestamptz not null default now()
);
create index if not exists idx_website_request_files_request
  on public.website_request_files(request_id, created_at);
alter table public.website_request_files enable row level security;

-- Private bucket. Files are written and read (via short-lived signed links) by the
-- backend only.
insert into storage.buckets (id, name, public)
values ('website-uploads', 'website-uploads', false)
on conflict (id) do nothing;
