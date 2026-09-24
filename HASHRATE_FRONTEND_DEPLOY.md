# XERA Hashrate Frontend Deploy

This build adds a dedicated **Hashrate** tab to the XERA frontend with five visual plan cards, XERA logo treatment, allocation status, 65M warning / 70M closure messaging, active-session display, and Paystack purchase handoff.

## Netlify

The repository already contains `netlify.toml` with:

- Base directory: `hub-frontend`
- Build command: `npm run build`
- Publish directory: `dist`
- Node 20

For an existing Netlify site, deploy the updated project through the site's production deploy flow. Netlify can build a project that still needs its build step when you are logged in. See the official Netlify deployment docs.

## Database migration

Apply `supabase/migrations/20260923_xera_hashrate_v1.sql` in the Supabase SQL editor. It is safe to re-run (every statement is idempotent), so if an earlier version of this file was already applied, run it again to pick up the latest fixes. The last section revokes `EXECUTE` on every `xera_*` function from `anon`/`authenticated` — **this must be applied before going live**; without it, anyone with the public anon key can call these functions directly.

## Backend environment variables

| Variable | Purpose |
| --- | --- |
| `XERA_PAYSTACK_SECRET_KEY` | Paystack secret key (required for checkout and webhook signature checks) |
| `XERA_HASHRATE_PAYMENTS_ENABLED` | Set to `true` to open Paystack purchases. While unset/false the Buy buttons show "Opening soon" |
| `XERA_HASHRATE_CALLBACK_URL` | Where Paystack returns the customer after checkout, e.g. `https://evoshub.xyz/xera`. The page reads `?reference=` and waits for activation |
| `XERA_HASHRATE_CRYPTO_ENABLED` | Leave unset — crypto payment-in is not implemented |

Set the Paystack webhook URL (Paystack dashboard → Settings → API Keys & Webhooks) to `https://<your-api-domain>/api/xera/hashrate/webhooks/paystack`.

Paystack requires a customer email; the backend uses the email on the person's XERA account.

## Required backend endpoints

The frontend expects the existing API to expose:

- `GET /api/xera/hashrate/tiers`
- `GET /api/xera/hashrate/sessions`
- `POST /api/xera/hashrate/purchase`
- `POST /api/xera/hashrate/sessions/{session_id}/claim`

The backend must have the XERA hashrate migration applied before the UI can load real plans.

## Payment note

The frontend only starts a Paystack checkout when the backend explicitly enables XERA hashrate payments. Crypto remains disabled until its backend payment-in verification is configured.
