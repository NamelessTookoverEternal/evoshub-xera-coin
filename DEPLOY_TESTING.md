# Deploying this for a test round — Netlify (frontend) + Fly.io (backend)

This covers getting the web app (NOT the smart contracts — those stay on
testnet/local until you're past this step) live on Netlify + Fly.io so you
can click through it end-to-end before anything public happens.

## 1. Backend first — Fly.io

```bash
cd evoshub-main
fly launch --no-deploy   # detects fly.toml + Dockerfile already in the repo; say no to overwriting them
fly secrets set \
  SUPABASE_URL=https://YOUR_PROJECT.supabase.co \
  SUPABASE_ANON_KEY=your-anon-key \
  SUPABASE_SERVICE_ROLE_KEY=your-service-role-key \
  XERA_TOKEN_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  ADMIN_TOKEN_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  XERA_CLAIM_SIGNER_PRIVATE_KEY=$(python3 -c "from eth_account import Account; print(Account.create().key.hex())") \
  BNB_RPC_URL=https://data-seed-prebsc-1-s1.binance.org:8545 \
  BNB_CHAIN_ID=97 \
  ALLOWED_ORIGINS=http://localhost:5173
fly deploy
```

Note the app's URL (`fly status` or the deploy output) — something like
`https://evoshub.fly.dev`. You'll need it in step 2.

Run the Supabase migrations first if you haven't (SQL Editor or
`supabase db push`, in order — see `supabase/migrations/`), against
whichever Supabase project you pointed `SUPABASE_URL` at above.

## 2. Frontend — Netlify

1. Push this repo to GitHub/GitLab (or `netlify deploy` from the CLI).
2. In Netlify: "Add new site" -> import the repo. `netlify.toml` at the repo
   root already sets the base directory, build command, and publish path -
   you shouldn't need to change anything in the UI.
3. Under **Site settings -> Environment variables**, add:
   - `VITE_API_BASE_URL` = the Fly.io URL from step 1 (e.g. `https://evoshub.fly.dev`)
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_ANON_KEY`
4. Deploy. Note the Netlify URL (e.g. `https://your-site-name.netlify.app`).

## 3. Wire the two together

Two things only work once both URLs are known — go back and set them now:

- **On Fly**, update `ALLOWED_ORIGINS` to include the real Netlify URL:
  ```bash
  fly secrets set ALLOWED_ORIGINS=https://your-site-name.netlify.app,http://localhost:5173
  ```
  Without this, every API call from the deployed frontend fails CORS —
  this is far and away the most common first-deploy issue.

- **On Netlify**, `netlify.toml`'s Content-Security-Policy `connect-src`
  already includes `https://*.fly.dev`, so no change needed there unless
  you're using a custom Fly domain — then add it to `connect-src` in
  `netlify.toml` and redeploy.

## 4. Smoke test

- Load the Netlify URL, open browser devtools -> Network tab, confirm API
  calls go to your `.fly.dev` URL and return 2xx, not CORS errors.
- `/xera` -> mining page loads and can reach the backend.
- `/admin-login` -> confirms it also reaches `.fly.dev`, not the old stale
  `onrender.com` URL that was hardcoded in a couple of files before this
  pass (now fixed — see below).
- Contact form / website-creation intake form submit successfully.

## What this round does NOT cover

- **No smart contracts are deployed here.** The BNB/TON contracts
  (`blockchain/bnb/`, `blockchain/ton/`) are a separate track — testnet
  deployment per `BLOCKCHAIN_INTEGRATION.md`'s checklist, independent of
  this web app test. The backend's `/api/xera/claim/*` routes exist and
  are tested, but calling them for real requires deployed contracts +
  `XERA_CLAIM_SIGNER_PRIVATE_KEY` pointed at a real signer, plus (for TON)
  the still-unwired `claims.py` TON branch — don't expect the on-chain
  claim button to work end-to-end yet.
- **No production domain.** Everything above uses Netlify's `*.netlify.app`
  and Fly's `*.fly.dev` subdomains on purpose, so you can test freely
  before pointing `evoshub.xyz` / `api.evoshub.xyz` at anything.

## Issues fixed during this production-readiness pass

For the record (so you know what changed and why), this pass found and
fixed real bugs beyond just adding config files:

- `hub-frontend/src/js/admin-login.js` and `admin-website-chat.js` had a
  **hardcoded stale backend URL** (`https://evoshub-xera-coin.onrender.com`)
  that ignored all configuration — the admin panel would have silently
  called the wrong backend no matter what you set `VITE_API_BASE_URL` to.
  Fixed to use the same configurable pattern as the rest of the app.
- `website-request-form.js` / `contact-form.js` read
  `import.meta.env.VITE_API_BASE_URL` with **no fallback** — if that env
  var wasn't set, requests went to literally `"undefined/api/..."`. Now
  falls back the same way `xera.js` already did.
- `xera.js` / `xera-chain.js` / `xera-public.js` all previously hardcoded
  `https://api.evoshub.xyz` as their only non-localhost fallback — with no
  domain live there yet, this would have silently pointed the deployed
  frontend at a nonexistent host. Now all five files above read the same
  `VITE_API_BASE_URL` env var first.
- One genuine test bug in `blockchain/bnb/test/XeraVesting.test.js`
  (not a contract bug) — Hardhat auto-mines with an advancing timestamp,
  so "premature release" couldn't actually be observed at exactly t=0 the
  way the old test assumed. Replaced with two tests that check the real,
  observable behavior instead. All 30 Hardhat tests pass now.
- Added the missing `.gitignore`, `python/.env.example`,
  `hub-frontend/.env.example`, and `netlify.toml` — none of these existed
  before, so there was no committed record of what env vars a fresh
  deploy actually needs.
- `main.py` now calls `load_dotenv()` so a local `.env` file actually
  gets picked up (the dependency was already in `requirements.txt` but
  never invoked).

---

## Wallet connection + claim flow (BNB / TON) — setup and diagnostics

### 1. Apply the new migration
Run `supabase/migrations/20261003_xera_wallet_connection_methods.sql` (after 20260912 and 20260914).
It is additive and safe to re-run. It adds `connection_method` (`wallet` | `manual`) to the existing
`xera_external_wallets` table — no new wallet table. Until it is applied, reads keep working but
"add manual address" / "remove wallet" will fail.

### 2. New / changed environment variables (backend)
| Variable | Purpose |
|---|---|
| `XERA_BNB_CHAIN_ID` | Expected BNB chain: `97` testnet, `56` mainnet. One source of truth for both the claim signature's EIP-712 domain **and** the network the UI asks the wallet to be on. Legacy `BNB_CHAIN_ID` is still honoured. Default `97`. |
| `XERA_BNB_RPC_URL` | Server-side RPC used to verify a claim transaction. Legacy `BNB_RPC_URL` still honoured. **Never sent to the browser.** |
| `XERA_BNB_PUBLIC_RPC_URL` | Optional. Public RPC offered to the wallet's "add network" prompt (defaults to the standard public BSC endpoint for the chain). |
| `XERA_TON_PROOF_DOMAINS` | Optional, comma-separated. Domains a TON ownership proof may be issued for. Defaults to the hosts in `ALLOWED_ORIGINS`. |
| `XERA_TON_PROOF_MAX_AGE_SECONDS` | Optional, default `900`. |
| `XERA_TON_TESTNET` | `true` to render TON display addresses in testnet form. |

### 3. Frontend
* New npm deps: `@tonconnect/ui` (TON connect modal) and `ethers` (claim transaction; lazy-loaded, not in the initial bundle).
* `hub-frontend/public/tonconnect-manifest.json` — change `url`/`iconUrl` to the real site origin if it is not `https://evoshub.xyz`.
* CSP `connect-src` (netlify.toml ×2, vercel.json) now allows the TonConnect wallet list/bridges. If a particular TON wallet fails to connect, check the browser console for a blocked `connect-src` host and add it.

### 4. Why might `POST /api/xera/claim/sign` return 404 in production?
The route is defined in `python/xera/routes_chain.py` and registered in `python/main.py`; booting the source
and sending `OPTIONS`/`POST` reaches the handler (401 without a token). A 404 therefore means the **running**
service isn't this code, or the browser is calling a different host. Check, in order:

```bash
# 1. Does the running build contain the route? (new fields on GET /)
curl -s https://<api-host>/ | python3 -m json.tool
#    -> "xera_claim_sign_registered": true   and   "build": "<commit sha>"
#    field missing  => the service is running an OLDER build than this repo.
#    false          => wrong code/root directory deployed.

# 2. Preflight + POST reach the handler (expect 200 and 401, never 404)
curl -si -X OPTIONS https://<api-host>/api/xera/claim/sign \
  -H 'Origin: https://evoshub.xyz' -H 'Access-Control-Request-Method: POST' | head -5
curl -si -X POST https://<api-host>/api/xera/claim/sign -H 'Content-Type: application/json' \
  -d '{"reference_id":"x","chain":"BNB"}' | head -3
```
Then confirm the host the frontend actually calls (`VITE_API_BASE_URL` at build time) is the same service you just
checked, and — on Render — that the service's **Root Directory** is `python/` (or that it builds the root `Dockerfile`),
that it tracks the right branch, and that the latest deploy actually finished (trigger "Clear build cache & deploy").
