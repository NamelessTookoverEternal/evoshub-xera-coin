# EVOSGPT inside the Hub

EVOSGPT now runs inside the Hub, the same way EVOS Data does. No outside link, no second backend.

| Piece | Where |
|---|---|
| Backend | `python/services/evosgpt/core.py`, mounted at **`/api/evosgpt`** by `python/routes/evosgpt.py` (called from `main.py`) |
| Currency | `python/services/evosgpt/currency.py`, `GET /api/evosgpt/currency` |
| Frontend | `evosgpt/evosgpt-frontend`, built into `dist/evosgpt` and served at **`/evosgpt`** (`hub-frontend/scripts/build-evosgpt.mjs`) |
| Database | unchanged (`users.evosgpt_tier`, `evosgpt_*` tables). **No migration to run.** `evosgpt/supabase/schema_reference.sql` is for reference |
| Tests | `python/tests/evosgpt/test_evosgpt.py` |

## Environment variables (Render backend)
| Variable | Needed? | Notes |
|---|---|---|
| `OPENAI_API_KEY` | **Yes** | chat, images, documents. Without it the Hub still boots; chat returns an error |
| `PAYSTACK_SECRET_KEY` | Already set for EVOS Data | EVOSGPT reuses it. Set `EVOSGPT_PAYSTACK_SECRET_KEY` only if EVOSGPT uses a different Paystack account |
| `XERA_TOKEN_SECRET` | Already set | signs the session token EVOSGPT now uses |
| `EVOSGPT_APP_URL` | Optional | default `https://evoshub.xyz/evosgpt`; Paystack returns the customer here |
| `EVOSGPT_ENABLED` | Optional | `false` boots the Hub without EVOSGPT |

`SUPABASE_URL` / `SUPABASE_KEY` / `SUPABASE_ANON_KEY` are no longer needed for EVOSGPT: it uses the Hub's shared Supabase client (same as EVOS Data). Frontend: nothing new, it reuses `VITE_API_BASE_URL`.

## Currency
Default is **GHS**. The visitor's country comes from their IP (a VPN exit country counts), first from the Hub edge (`/api/country`), else from the backend. Prices on the home and upgrade pages and the AI's own answers then use that country's currency.
- Display only: Paystack still bills in GHS, and the page says so.
- Rates come from open.er-api.com, cached 6 hours. If no rate has ever loaded, everyone sees GHS. A price is never invented.

## What changed in behaviour
- **Auth fixed.** The old backend trusted a `user_id` sent by the browser (anyone could read another user's chats or upgrade themselves). Every user route now needs the Hub session token for that same user. Login returns it; a Hub-signed-in visitor is signed in to EVOSGPT automatically.
- Existing sessions on the old site have no token: users sign in once again. Sessions last 24h (Hub rule).
- **Payments.** Upgrades are confirmed with Paystack when the customer returns (`/upgrade/verify`), checking amount and currency, so they work even if the Paystack dashboard webhook points at EVOS Data's URL. The EVOSGPT webhook is **`/api/evosgpt/webhook/evosgpt-paystack`** (its own name, separate from EVOS Data's `/webhook/paystack`; the old `/api/evosgpt/webhook/paystack` still works as an alias). It can no longer grant Founder. Paystack allows one webhook URL per account, so if both products share an account, `/upgrade/verify` is what completes EVOSGPT upgrades.
- Login accepts only plain username/email characters (it was building a filter string from raw input).
- The inline third-party analytics snippet is not in the Hub build (the Hub CSP blocks inline scripts).
- The app hub's EVOSGPT card opens `/evosgpt`.

## Go live
1. Set `OPENAI_API_KEY` on Render, redeploy the backend and the frontend.
2. Check `https://<api>/api/evosgpt/` returns `{"status":"ok", ...}` and `/evosgpt` loads.
3. Keep evosgpt.xyz on the old backend until you are happy, then point/redirect it to `https://evoshub.xyz/evosgpt` (not done here).
