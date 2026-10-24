# XERA first-transfer readiness: KYC status + one-time fee

What is **implemented**, what is **pending configuration**, and what is **still a business decision**.
Nothing here changes mining, rewards, the 25% / 75% split, entitlements, referrals, tokenomics or the
BNB / TON claim flows themselves.

## 1. What a user must have before their first transfer

| # | Requirement | Where it is enforced |
|---|---|---|
| 1 | KYC **Verified** | `xera/readiness.py` -> called from `xera/chain/claims.py` (`sign_amount_claim`, `retry_claim`, legacy `sign_claim`) and `xera/chain/migration.py` (`prepare_claim`) |
| 2 | One-time fee **Paid** | same gate |
| 3 | External wallet verified (wallet proof) | unchanged, `claims._get_verified_wallet`. **Passing 1 and 2 never skips it.** |
| 4 | Existing claim eligibility (balance, minimum, allocation cap) | unchanged |
| 5 | Chain / contract configured and `onchain_enabled` | unchanged, `config.require_onchain_enabled`. **Mainnet stays closed until that flag is set.** |

The gate sits at the backend boundary, so a direct API call cannot skip it. Failure returns HTTP 403:

```json
{"detail": {"code": "first_transfer_requirements_incomplete", "missing": ["kyc", "fee"], "message": "..."}}
```

Mining, wallet linking and every read-only status call are **not** gated.
Exempt: the admin on-chain pilot only (`admin_pilot_mode()`, entered solely by `routes_admin_chain.py`
after the live admin check and only when `XERA_ADMIN_ONCHAIN_PILOT=true`). User routes never enter it.

## 2. Files

New
- `supabase/migrations/20261024_xera_kyc_fee_readiness_v1.sql` - tables + two functions (see section 4)
- `python/xera/readiness.py` - KYC + fee logic and the gate
- `python/xera/routes_readiness.py` - user + admin routes
- `python/tests/test_readiness.py` - 33 tests
- `hub-frontend/src/js/xera-readiness.js`, `src/css/xera-readiness.css` - cards + modals
- `hub-frontend/src/pages/admin-xera-kyc.html`, `src/js/admin-xera-kyc.js` - admin review queue

Changed (small)
- `python/main.py` - mounts the two routers
- `python/xera/chain/claims.py` - gate call + `ClaimRequirementsError`
- `python/xera/chain/migration.py` - gate call in `prepare_claim`
- `python/xera/chain/config.py` - `admin_pilot_active()` helper
- `python/xera/routes_chain.py` - maps the gate error to the 403 above
- `python/xera/routes_hashrate.py` - the one shared Paystack webhook hands `xera-fee-` references to the fee code
- `python/tests/conftest.py` - older tests switch the gate off (it is ON by default in production)
- `hub-frontend/src/pages/xera/index.html` - the card containers
- `hub-frontend/src/js/xera.js` - one import + one call (display only)
- `hub-frontend/src/js/xera-chain.js` - passes the 403 to the requirements modal
- `hub-frontend/vite.config.js`, `src/pages/admin-website-chat.html` - register + link the admin page

## 3. API

User (XERA token): `GET /api/xera/readiness`, `POST /api/xera/kyc/submit`, `POST /api/xera/fee/checkout`,
`GET /api/xera/fee/verify?reference=`, `GET /api/xera/notifications`, `POST /api/xera/notifications/read`.
Admin (active admin agent): `GET /api/admin/xera/kyc?status=`, `POST /api/admin/xera/kyc/{user_id}/review`.
Paystack: the existing `POST /api/xera/hashrate/webhooks/paystack` (one webhook URL per Paystack account).

## 4. Database - run manually

Run `supabase/migrations/20261024_xera_kyc_fee_readiness_v1.sql` in the Supabase SQL editor.

- Only **adds** tables, indexes and functions; safe to re-run; no data is changed or deleted.
- `xera_kyc` (current KYC status per user), `xera_fee_payments` (one row per attempt, unique reference,
  and a unique index allowing **one PAID row per user**), `xera_readiness_events` (audit),
  `xera_notifications` (server-written).
- `xera_confirm_fee_payment()` is idempotent (PENDING -> PAID once) and refuses a mismatched amount/currency.
- RLS is on; everything is revoked from `anon` / `authenticated`; only `service_role` (the backend) can read or write.
  A user therefore cannot set their own KYC to Verified or their fee to Paid.

Check afterwards:
```sql
select tablename, rowsecurity from pg_tables where tablename in ('xera_kyc','xera_fee_payments','xera_readiness_events','xera_notifications');
```

**The SQL has not been run against a real Postgres in my environment.** The Python tests use an in-memory
stand-in that follows the same rules. Run the migration on a staging project (or a copy) first.

## 5. KYC provider requirements (pending configuration)

There is **no KYC provider in the repo and no credentials**, so none is pretended.
What works today is **manual review**:
1. The user submits legal name, country, ID type and the **last 4 characters** of the ID number (nothing else; no images).
2. An active admin agent opens **/admin-xera-kyc.html** and chooses Verify / More info / Fail (a note is required for the last two).
3. The decision, the admin id and the time are recorded; the user gets a notification.

Honest limit: the reviewer sees only those fields, so "Verify" is only as good as the check you do outside the app
(e.g. through support). For real identity assurance, add a provider (Smile ID, Sumsub, Onfido, etc. - your choice). It needs:
a provider account + API credentials in Render env vars, a hosted verification link started by the backend, and a
**signed callback endpoint** that sets `xera_kyc.status` (set `provider` / `provider_reference`). The table and the gate
already support this; only the start + callback routes are missing. Do not store ID images unless required; if you must,
use a private bucket, admin-only access and a retention period.

Data-protection: you are collecting personal data. Check the Ghana Data Protection Act, 2012 (Act 843) obligations
(registration with the Data Protection Commission, privacy notice, retention) before launch. This is not legal advice.

## 6. Fee, Paystack and refund blockers

- **Amount/currency:** the fee is `XERA_FEE_AMOUNT` (default `1.00`) in `XERA_FEE_CURRENCY` (default `USD`). The existing
  hashrate prices are billed in **GHS**. Your Paystack account must be allowed to charge **USD** ("international payments"
  is a different setting). If Paystack refuses, checkout fails with "Nothing was charged" and the attempt is marked FAILED;
  the code **never** switches currency. Confirm USD in the Paystack dashboard or with a test-key payment.
- **Verified server-side:** a payment only counts after the backend re-checks it with Paystack AND the amount + currency equal the attempt's
  (checked again in SQL). The redirect back from checkout proves nothing.
- **Collection is OFF** unless `XERA_FEE_COLLECTION_ENABLED=true` **and** `XERA_FEE_REFUND_POLICY` has text (shown to the user
  before paying). Until both are set, the card says "Payment is not open yet."
- **Business decisions that are yours:** refund policy wording; whether $1 is refundable if a transfer fails; consumer-disclosure
  and tax/receipt requirements; Paystack's own terms for this fee type. Write the policy before turning collection on.
- Duplicate webhooks cannot grant two entitlements; if a user somehow paid twice, the second is logged as CRITICAL for a manual refund.

## 7. Environment variables

| Name | Default | Purpose |
|---|---|---|
| `XERA_FIRST_TRANSFER_GATE` | `true` | Set `false` only to switch the gate off entirely (not recommended) |
| `XERA_FEE_COLLECTION_ENABLED` | `false` | Live fee collection on/off |
| `XERA_FEE_REFUND_POLICY` | empty | Refund-policy text; collection stays closed while empty |
| `XERA_FEE_AMOUNT` | `1.00` | Fee amount |
| `XERA_FEE_CURRENCY` | `USD` | Fee currency |
| `XERA_FEE_CALLBACK_URL` | none | Where Paystack returns the customer, e.g. `https://evoshub.xyz/xera` |
| `XERA_PAYSTACK_SECRET_KEY` | existing | Already used for hashrate; same key signs the webhook |

## 8. Security review (summary)

- No endpoint accepts a KYC or fee status from the browser; extra fields in the submit body are ignored (tested).
- KYC and fee state live in tables only the service-role backend can touch; admin review re-checks `admin_agents` on every call.
- A user cannot pay for or verify via another user's reference (`/fee/verify` returns 404 for someone else's payment).
- Webhook: HMAC-SHA512 signature (constant-time compare), then re-verification with Paystack, then amount + currency match.
- Only the last 4 characters of an ID number are stored; admin page renders user text as plain text (no HTML injection).
- Secrets: no keys in the frontend; the service-role key stays on the backend.
- Known gap: manual review depends on out-of-app checks (see section 5).

## 9. Tests

`python/tests/test_readiness.py` - 33 tests, all passing: gate blocks on missing KYC / fee / both and on PENDING, FAILED,
MORE_INFO, failed or stale fee; verified + paid still hit the wallet check; closed chain stays closed; retry and migration
paths gated; forged status ignored; admin-only review; frontend success redirect and failed payments never mark paid; duplicate
webhooks grant once; wrong amount/currency rejected; one user's payment cannot satisfy another; collection off by default and
off without a refund policy; Paystack refusing USD does not switch currency; notifications are per user; mining code does not
reference the gate.
Whole backend suite (excluding `tests/evosdata`, which exits at import): 300 passed, 3 failed, 108 errors; the 3 failures and
108 errors are identical **before** my changes (missing EVOS Data / EVOSGPT settings and unfinished token-refresh work), and
passes rose from 267 to 300 (my 33).
Browser check (headless Chromium against a mock API): cards render server states, KYC and fee modals, requirements modal opens
and closes, mining timer unaffected, admin review page works. **Not run:** the SQL in a real Postgres; a real Paystack test
payment; mobile devices.

## 10. Deployment checklist

1. Run the migration (staging first).
2. Deploy the backend and frontend.
3. Leave `XERA_FEE_COLLECTION_ENABLED` unset. Confirm the dashboard shows the three cards and "Payment is not open yet."
4. Submit a KYC as a test user, review it at `/admin-xera-kyc.html`, confirm the notification.
5. With Paystack **test** keys: write `XERA_FEE_REFUND_POLICY`, set `XERA_FEE_COLLECTION_ENABLED=true`, `XERA_FEE_CALLBACK_URL`,
   make one test payment, confirm it shows Paid and a second webhook changes nothing. Confirm USD is accepted.
6. Only then switch to live keys.
7. Keep `onchain_enabled=false` for users until you intend to open claiming.

## 11. Remaining blockers

KYC provider (or accept manual review); USD charging confirmed on Paystack; refund policy + disclosures written;
Data Protection registration/privacy notice; the SQL run on a real database; the same flow tested on a phone.
Not touched, by request: TON testnet claims, crypto hashrate payments.
