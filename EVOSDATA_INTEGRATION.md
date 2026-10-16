# EVOS Data Services — merged into EVOS Hub

One repository, **one FastAPI application** (`python/main.py`), one Docker image / backend service, one Supabase project, one login.

## 1. Summary
- Evosdata's backend (`evosdata/main.py`, ~6,200 lines) is now a package inside the Hub backend: `python/services/evosdata/` (`core.py` = the former `main.py`, plus `spin`, `agent_fee`, `dashxera`, `evoxera_bot`, `admin_auth`). Every `@app.<verb>` became `@router.<verb>`; route bodies, request/response shapes, provider fallbacks, Paystack/provider webhook handlers and retry loops are unchanged. All **63 original routes** are registered (checked programmatically) plus the 22 spin / agent-fee / DashXera / bot routes.
- Mounted by the existing entry point: `python/main.py` → `mount_evosdata(app)` (`python/routes/evosdata.py`). Everything lives under **`/api/evosdata/*`**, so nothing collides with Hub or XERA routes. Webhook paths (`/webhook/*`, `/whatsapp/*`, `/ussd`) are *also* registered at their old root paths (same handlers, no double processing) so you can point `api.evosdata.xyz` at this backend without touching any provider dashboard.
- The React app is built into the Hub at `/evosdata` (`hub-frontend/scripts/build-evosdata.mjs`) and talks only to `<Hub API>/api/evosdata`. The embedded bundle contains **no** `evos-data-services.fly.dev`, `api.evosdata.xyz` or other standalone host (verified by grep). The standalone site still builds with its old defaults.
- Shared login: Hub login → `/evosdata` → `POST /api/evosdata/auth/hub-session` (Hub token verified server-side, account read from `users`). The Hub token itself becomes the user/agent token; every protected Evosdata endpoint re-verifies it. No second login, no second long-lived token. The old two-service handoff (`HUB_SSO_SECRET`, `/api/auth/handoff`, `/auth/sso/exchange`) was removed — it is unnecessary in one process.
- XERA: `/xera` untouched. `XeraPromo.jsx` (existing from the previous pass) shows "XERA Token — Coming Soon" as a card on home/dashboard and a once-a-week dismissible popup only on those pages; never on shop/checkout/payment/login/agent pages.

## 2. Main files changed
| Area | Files |
|---|---|
| Backend merge | `python/services/evosdata/{core,db,admin_auth,spin,agent_fee,dashxera,evoxera_bot}.py` (new), `python/routes/evosdata.py` (new), `python/main.py` (mount + CORS headers), `python/requirements.txt` (+`requests`, `python-multipart`) |
| Auth | `core.py` (`_hub_session_uid`, Hub-aware `verify_user_token/verify_agent_token`, `/auth/hub-session`), `hub-frontend/src/js/{evos-session,xera}.js` (logout also clears Evosdata keys) |
| Frontend | `evosdata/evos-frontend/src/{config.js,api.js,App.jsx,lib/*,components/XeraPromo.jsx,…}`, `vite.config.js`, `index.html`+`public/splash-init.js` |
| Hub build/deploy | `hub-frontend/scripts/build-evosdata.mjs`, `hub-frontend/netlify/functions/bundlesProxy.mjs`, `netlify.toml`, `hub-frontend/vercel.json`, `Dockerfile` (comment only) |
| Tests | `python/tests/test_evosdata_hub_session.py` (new), `python/tests/evosdata/` (the three Evosdata suites, adapted to the new module paths) |
| Removed | standalone backend files (`evosdata/main.py`, `Dockerfile`, `fly.toml`, `requirements.txt`, module copies) — they live in `python/services/evosdata/` now. `evosdata/` keeps the frontend, `supabase/` migrations and docs. |

## 3. Confirmation: one backend
`python/main.py` is the only FastAPI application (`grep -rn "FastAPI(" python evosdata` → only `main.py`). Evosdata has no `app`, no Dockerfile, no second start command. The existing root `Dockerfile` (`COPY python/`, `uvicorn main:app`) already includes the new package — no change needed beyond requirements.

## 4. Database
No schema change, no new tables. Evosdata keeps using its existing tables (`users`, `orders`, wallets/transactions, agent tables…) through the same Supabase project; XERA tables are untouched and never referenced by Evosdata code. Evosdata now uses the **Hub's service-role client** (`utils/xera_supabase`), i.e. `SUPABASE_KEY` is no longer needed. **You must confirm Hub and Evosdata use the same Supabase project** (compare the `SUPABASE_URL` values). If they differ, set `EVOSDATA_SUPABASE_URL` + `EVOSDATA_SUPABASE_KEY` and Evosdata will use its own client; the Hub-login link between the two will then not work until users are migrated. Existing migrations are in `evosdata/supabase/migrations/` (already applied in production per the standalone app; not re-run here).

## 5. Environment variables for the existing Hub Render backend
Names only. "Same value" = copy the value from the standalone Evosdata service.
| Variable | Action | Notes |
|---|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY` | **Retain** | Do not overwrite. Verify `SUPABASE_URL` equals the Evosdata one. |
| `XERA_TOKEN_SECRET` | Retain | Signs Hub sessions — also what Evosdata now verifies. Never put in a frontend. |
| `ADMIN_TOKEN_SECRET` | Retain / verify | Name exists in both apps and is meant to be one shared admin secret — values must be identical. |
| `ALLOWED_ORIGINS` | Retain | Must include `https://evoshub.xyz`. |
| `ADMIN_SECRET` | **Add** (same value) | Evosdata admin header + legacy token signing (so existing logins keep working). Required. |
| `PAYSTACK_SECRET_KEY` | **Add** (same value) | Evosdata payments + webhook signature. Keep **separate** from `XERA_PAYSTACK_SECRET_KEY`. |
| `DATAMART_API_KEY`, `DATAMART_WEBHOOK_SECRET` | Add | Required. |
| `BUNDLES_GHANA_API_KEY`, `BUNDLES_GHANA_API_SECRET` | Add | Required by the startup check (also set on Netlify, see below). |
| `MOOLRE_USERNAME`, `MOOLRE_API_KEY`, `MOOLRE_ACCOUNT_NUMBER` (`MOOLRE_BASE` optional) | Add | Required. |
| `SWIFT_DATA_LINK_API_KEY` (`SWIFT_DATA_LINK_BASE`, `SWIFT_DATA_LINK_WEBHOOK_URL` optional) | Add | Webhook URL now defaults to `$HUB_API_PUBLIC_URL/api/evosdata/webhook/swiftdatalink`. |
| `AGYEKUMDATA_API_KEY`, `AGYEKUMDATA_WEBHOOK_SECRET` (`AGYEKUMDATA_BASE` optional) | Add | Required. |
| `SMTP_PASSWORD` (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER` optional) | Add | Required. Distinct from Hub's `EMAIL_*`. |
| `AFA_AGENT_PRICE`, `AFA_SELL_PRICE`, `AFA_WEBHOOK_URL`, `SPIN_DAILY_CAP_GB`, `PAYSTACK_LOW_BALANCE_GHS`, `PROVIDER_FAILURE_THRESHOLD` | Add if set today | Optional tuning; defaults are in code. |
| `WA_TOKEN`, `WA_PHONE_NUMBER_ID`, `WA_VERIFY_TOKEN`, `WA_APP_SECRET`, `WA_OWNER_NUMBER`, `WA_GRAPH_VERSION` | Add if bot is used | Bot stays off without them. |
| `HUB_API_PUBLIC_URL` | Add (optional) | Public base of this backend, e.g. `https://api.evoshub.xyz`. |
| `BUNDLES_PROXY_SECRET`, `BUNDLES_GHANA_BASE` | Add (recommended / optional) | Secret shared with the Netlify proxy function; base defaults to `https://evoshub.xyz/.netlify/functions/bundlesProxy`. |
| `EVOSDATA_ENABLED` | Optional | `false` boots the Hub without Evosdata. Default `true` (fail-fast on missing vars). |
| `EVOSDATA_BACKGROUND_JOBS` | Optional | `false` = routes mounted, retry loops not started (use while the standalone backend still runs). |
| `EVOSDATA_SUPABASE_URL`, `EVOSDATA_SUPABASE_KEY` | Only if different Supabase project | Backend-only. |
| **Do not copy:** `SUPABASE_KEY`, `HUB_SSO_SECRET`, `FRONTEND_URL`, `EXTRA_ALLOWED_ORIGINS`, `DASHXERA_MAIN_MODULE` | — | No longer used. |

**Hub Netlify site (frontend + proxy function):** `VITE_API_BASE_URL` = the Hub API's public URL (also becomes the Evosdata API host at build time); for the Bundles Ghana proxy function add `BUNDLES_GHANA_API_KEY`, `BUNDLES_GHANA_API_SECRET`, `BUNDLES_PROXY_SECRET` (same value as backend). Vite variables are public build-time values; nothing secret belongs in them.

## 6. Build and test results (what was actually run)
| Check | Result |
|---|---|
| `pip install -r python/requirements.txt` (pinned, clean venv) | OK — no version conflicts (`fastapi 0.111.0`, `pydantic 2.7.1`, `slowapi 0.1.9`, `bcrypt 4.0.1`, `requests 2.32.3`) |
| App import/startup through `main:app`, uvicorn run from a copy of `python/` (the Docker `COPY`), probed with curl | OK — `/`, `/api/evosdata/`, 401 on `hub-session` without token, CORS preflight allows `X-Agent-Token/X-User-Token/X-Admin-Secret`, legacy webhook aliases respond |
| Route registration | 167 routes, no duplicate path+method; all 63 original Evosdata routes present under `/api/evosdata`; XERA routes present |
| Hub pytest suite + new tests | **205 passed** (192 existing Hub/XERA + 13 new: Hub-session auth, wrong-user/unapproved-agent rejection, webhook aliases, callback allow-list, feature toggles) |
| Evosdata's own suites (dashxera, bot, spin/agent-fee) | All pass against the merged modules (65 checks + dashxera + bot) |
| Hub frontend build incl. embedded Evosdata | OK; `/evosdata` output has no standalone backend hosts |
| Standalone Evosdata frontend build | OK (unchanged defaults) |
| **Not run:** Docker build (no Docker in the sandbox — equivalent steps were run instead), browser click-through of `/evosdata` refresh/deep links, Netlify rewrites, real Supabase, real Paystack/provider/WhatsApp calls, Render. **Nothing is verified in production.** |

## 7. Outstanding issues
- **Same-database caution:** while the standalone backend still runs against the production database, keep `EVOSDATA_BACKGROUND_JOBS=false` on the Hub, otherwise both would run the stuck-order/deposit/withdrawal retry loops. Webhooks should be delivered to exactly one backend at a time.
- **Bundles Ghana proxy** previously lived on the standalone site (a Netlify function); it is now `hub-frontend/netlify/functions/bundlesProxy.mjs` and the backend defaults to the Hub's copy. Confirm the Netlify env vars are set before enabling that provider, or set `BUNDLES_GHANA_BASE` back to the old URL temporarily.
- **Logout:** tokens are stateless. Hub logout clears the browser session and the 24h Hub token expires; a copied token stays valid until then (agent rights are re-checked live, so revoking an agent takes effect at once). Server-side revocation would need a session table — not added.
- Legacy Evosdata tokens (30-day user, non-expiring agent) are still accepted for the standalone site and old sessions; they were not changed.
- Pre-existing, **not changed** (would alter live behaviour): some Evosdata endpoints still trust a client-supplied `user_id` without a token (e.g. `/orders/me`, `/users/me`, `/today/{id}`); the admin secret doubles as the legacy token key. Worth a dedicated hardening pass.
- Registration still happens through Evosdata's `/auth/register`; the Hub-mounted login form delegates to the Hub login. Users with Evosdata-only passwords work because both read the same bcrypt `users` rows.
- Replay/rate-limit state is in memory (single instance). Scale-out needs shared storage.

## 8. Deployment steps (do in this order; nothing here has been done for you)
1. **Check the database link:** confirm `SUPABASE_URL` is identical on the Hub and standalone Evosdata services.
2. **Hub Render backend → Environment:** add the variables in §5. First deploy with `EVOSDATA_BACKGROUND_JOBS=false` (and, if you want a zero-risk first deploy, `EVOSDATA_ENABLED=false`). Keep every existing variable.
3. Deploy the backend from this repo (existing service, existing Dockerfile). Check `GET /` and `GET /api/evosdata/` return OK and the logs show `EVOSDATA: mounted at /api/evosdata`.
4. **Netlify (Hub site):** set `VITE_API_BASE_URL` and the three Bundles Ghana variables; deploy. Open `https://evoshub.xyz/evosdata`, refresh on a deep link, sign in via the Hub, confirm the account/agent dashboard loads without a second login, then log out in the Hub and confirm `/evosdata` is signed out. Use Paystack **test** keys / a staging copy for payment checks.
5. **Webhooks (cutover, needs your approval):** either (a) add `api.evosdata.xyz` as a custom domain on the Hub Render service so existing Paystack/DataMart/Swift/Agyekum/Moolre/WhatsApp URLs keep working, or (b) change each provider's webhook to `https://<hub-api>/api/evosdata/webhook/<name>` (Paystack: `/webhook/paystack`).
6. At cutover: stop (or disable webhooks on) the standalone backend, set `EVOSDATA_BACKGROUND_JOBS=true` on the Hub, redeploy.
7. Keep the standalone service and `evosdata.xyz` until you are satisfied; then retire them.
