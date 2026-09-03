# EVOS Business Hub — evoshub.xyz
Powered by EVOXERA TECHNOLOGY

## Structure
- `hub-frontend/` — Website (HTML · CSS · JS)
- `python/`       — Backend API (FastAPI) — add when needed

## Run frontend
```
cd hub-frontend && npm install && npm run dev
```

## Run backend
```
cd python && pip install -r requirements.txt && uvicorn main:app --reload
```

## Website Creation (chat-with-admin) feature

A new product page, `website-creation.html`, lets a visitor pick a package,
submit a request, and chat live with an EVOXERA agent — no custom backend
required, it's all Supabase (Postgres + Realtime + RLS).

### One-time setup
1. **Run the migrations** (in order) against your shared Supabase project,
   via the SQL Editor or `supabase db push`:
   - `supabase/migrations/20260709_website_creation.sql` — tables, RLS, realtime
   - `supabase/migrations/20260710_website_creation_ratelimits.sql` — abuse/flood protection
2. **Configure and run the backend** (`python/`) — the intake form POSTs to
   `/api/website-requests` rather than inserting directly, so the backend
   must be running. Copy `python/.env.example` to `python/.env` and fill in
   `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_SERVICE_ROLE_KEY` (the
   service_role key lives here only — never in frontend code or a build
   that ships to the browser), plus SMTP settings if you want admin email
   notifications. Then `cd python && pip install -r requirements.txt &&
   uvicorn main:app --reload`.
3. **Set frontend env vars** — copy `hub-frontend/.env.example` to
   `hub-frontend/.env` and fill in `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`
   (safe to expose — see the comments in `.env.example`) and
   `VITE_API_BASE_URL` (where the backend above is reachable). Live chat
   itself still talks to Supabase Realtime directly from the browser with
   the anon key; only the initial request submission goes through the
   backend.
4. **Grant agent access** — from the Supabase SQL editor (service_role, not
   the app), promote an existing shared-auth user to an agent for this
   product:
   ```sql
   insert into public.admin_agents (user_id, display_name)
   values ('<existing-auth-user-uuid>', 'Agent Name');
   ```
   That account can then sign in at `/admin-login.html` with its existing
   email/password and reach the inbox at `/admin-website-chat.html`.

### How the security model works
- **Intake form** is submitted to the FastAPI backend (`/api/website-requests`),
  not inserted directly from the browser. The backend independently
  re-verifies the visitor's Supabase access token against Supabase's own
  Auth server (never trusts a client-sent id), re-sanitizes every field with
  `bleach`, checks the honeypot field, and applies a per-IP rate limit
  (`5/hour` via `slowapi`) — a layer a purely client-side insert can't
  provide, since a bot can always mint a fresh anonymous session to dodge a
  per-visitor-id limit. It then inserts with the `service_role` key, so the
  DB-level constraints and triggers below are a second, independent line of
  defense, not the only one.
- **Live chat**, once a request exists, talks to Supabase Realtime directly
  from the browser using the anon key — RLS is the only gate there, which is
  fine because chat rows are small, structurally constrained, and
  rate-limited at the DB level (below).
- **Visitors** never get a real account — the browser calls
  `supabase.auth.signInAnonymously()` on first form interaction, which
  issues a real Supabase-signed session. Every row a visitor creates is
  stamped `visitor_id = auth.uid()` and every RLS policy checks that, so a
  visitor can only ever see their own request/thread.
- **Admins** are existing shared-auth accounts; whether an account is an
  agent is decided by row membership in `admin_agents`, checked via a
  `SECURITY DEFINER` function (`is_website_admin()`) — never by a
  client-supplied flag. The admin dashboard calls that same function before
  showing anything and signs out + redirects if it returns false.
- **DB-level abuse protection**: rate-limit triggers (max 3 requests/hour
  per visitor, max 20 chat messages/minute per sender) and server-side
  HTML-tag stripping on every text field, in addition to the frontend always
  rendering messages via `textContent` (never `innerHTML`) to prevent stored
  XSS.
- **Transport/headers**: `vercel.json` sets `X-Frame-Options`,
  `X-Content-Type-Options`, `Referrer-Policy`, and a `Content-Security-Policy`
  that only allows connections to Supabase and same-origin scripts. The
  backend's CORS is restricted to an explicit `ALLOWED_ORIGINS` allowlist.

## XERA Token (Coin) V1
XERA Token (Coin) is hosted by EVOS Business Hub at `/xera`. The active V1 features are XERA login, wallet, 24-hour server-authoritative mining, atomic claiming, ledger and transaction history. Purchases, withdrawals, transfers, referrals and on-chain features remain disabled.

Run `supabase/migrations/20260901_xera_token_v1.sql` against the shared Supabase project only after reviewing the existing `public.users` schema. Configure `python/.env` from `python/.env.example`; never commit secrets.

## Deploying the backend to Google Cloud Run

Cloud Run is the current recommended target for this backend (Fly.io and
Render both require a card and can suspend on billing failures; Cloud Run's
free tier is usage-based, so there's no subscription to fail). A GCP billing
account still requires a card for identity verification, but you can make
an actual charge mathematically impossible with the cap below.

### 1. One-time setup

```bash
# Install the gcloud CLI first: https://cloud.google.com/sdk/docs/install
gcloud auth login
gcloud projects create evoshub-xera --name="EVOS Hub XERA Backend"
gcloud config set project evoshub-xera
gcloud services enable run.googleapis.com cloudbuild.googleapis.com
```

You'll be prompted to link a billing account in the Cloud Console the first
time you enable these APIs — this is the one place a card is required.

### 2. Cap your spend before deploying anything

Do this **before** your first deploy, not after:

```bash
# Replace BILLING_ACCOUNT_ID with the id from:
#   gcloud billing accounts list
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="XERA hard cap" \
  --budget-amount=1.00USD \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=1.0
```

This alerts you by email at 50% and 100% of $1 spent. A budget alert does
**not** auto-stop billing by itself — for a true zero-risk guarantee, also
cap the service itself so it physically cannot scale past what the free
tier covers (see `--max-instances=1` in the deploy command below). Cloud
Run's free tier is 2 million requests and 360,000 GB-seconds of compute per
month — a single capped instance for a hobby project will not come close
to that.

### 3. Deploy

From the repo root (where this Dockerfile lives):

```bash
gcloud run deploy evoshub-xera-backend \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --max-instances=1 \
  --min-instances=0 \
  --memory=512Mi \
  --set-env-vars="ENVIRONMENT=production,ALLOWED_ORIGINS=https://evoshub.xyz,https://www.evoshub.xyz" \
  --set-env-vars="SUPABASE_URL=YOUR_SUPABASE_URL" \
  --set-env-vars="SUPABASE_ANON_KEY=YOUR_ANON_KEY" \
  --set-env-vars="SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY" \
  --set-env-vars="XERA_TOKEN_SECRET=YOUR_LONG_RANDOM_SECRET" \
  --set-env-vars="ADMIN_TOKEN_SECRET=YOUR_ADMIN_SECRET"
```

`gcloud` builds the Dockerfile via Cloud Build automatically — no manual
image push needed. The command prints a `*.run.app` URL when done.

Prefer not to put real secrets on your shell history? Use Secret Manager
instead of `--set-env-vars` for the five secret values:

```bash
echo -n "YOUR_SERVICE_ROLE_KEY" | gcloud secrets create supabase-service-role-key --data-file=-
gcloud run deploy evoshub-xera-backend \
  --source . \
  --update-secrets=SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest
  # ...repeat --update-secrets for each secret, alongside the plain
  # --set-env-vars for ENVIRONMENT/ALLOWED_ORIGINS which aren't sensitive
```

### 4. Point your domain at it

In Netlify's DNS panel for `evoshub.xyz`, add:

```
Type: CNAME
Host: api
Value: ghs.googlehosted.com
```

Then in the Cloud Console under Cloud Run → your service → **Manage Custom
Domains**, add `api.evoshub.xyz` and follow the verification steps (Google
Search Console domain ownership verification, then automatic SSL cert
issuance — usually live within 15-60 minutes).

Update the frontend's API base URL and the backend's `ALLOWED_ORIGINS` to
match once this is live.

