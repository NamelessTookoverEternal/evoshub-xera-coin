# Hybrid KYC: provider check + admin final decision

Flow: user presses KYC → picks country → **Smile ID** (first choice for every country) hosts the ID/passport + selfie
capture → provider result comes back by signed callback → the case appears for an admin → admin presses **Verify** → the
dashboard shows Verified. **Images never touch our servers or database.** Only the admin can set VERIFIED, and only when
the provider's result is APPROVED (enforced in `review_kyc` and by a DB CHECK).

## Routing
- Smile ID first for all countries. **Didit** is used when Smile ID can't start a session for that country, when Smile ID is off,
  and as a **second opinion after Smile ID declined the user** (the user taps "Continue to verification" again).
- Optional: `XERA_KYC_SMILEID_COUNTRIES=GH,NG,...` limits "Smile ID first" to those countries (others go to Didit first).
- The browser sends only the country code; the server chooses the provider.

## Rejected cases show in the admin page
`/admin-xera-kyc.html` has a **Provider rejected (n)** tab (API: `GET /api/admin/xera/kyc?status=PROVIDER_DECLINED`).
Each card shows provider, result, reason and reference. Verify is greyed out unless the provider result is APPROVED.
Before pressing Verify, open the case in the provider portal and check the ID and selfie yourself.

## Files (new / changed)
New: `python/xera/kyc_providers/{__init__,base,routing,didit,smileid}.py`, `python/xera/kyc_provider.py`,
`supabase/migrations/20261027_xera_kyc_provider_v1.sql`, `python/tests/test_kyc_provider.py`.
Changed: `python/xera/readiness.py`, `python/xera/routes_readiness.py`, `python/tests/conftest.py`,
`hub-frontend/src/pages/xera/index.html`, `src/js/xera-readiness.js`, `src/js/admin-xera-kyc.js`, `src/pages/admin-xera-kyc.html`.

## Environment variables (Render only; never in chat or the repo)
| Name | Purpose |
|---|---|
| `XERA_KYC_SMILEID_ENABLED=true`, `SMILEID_PARTNER_ID`, `SMILEID_API_KEY`, `SMILEID_CALLBACK_URL`, `SMILEID_PRIVACY_POLICY_URL` (public https) | Smile ID |
| `SMILEID_ENV` | `sandbox` (default) or `production` |
| `SMILEID_ID_TYPES` | JSON: country -> ID type names from Smile ID's ID Coverage page, e.g. `{"GH":["PASSPORT","GHANA_CARD"],"*":["PASSPORT"]}`. A country not listed (and no `*`) goes to the fallback provider |
| `SMILEID_VERIFICATION_METHOD` | default `document_verification` (name unconfirmed; copy the exact string from Smile ID) |
| `XERA_KYC_DIDIT_ENABLED=true`, `DIDIT_API_KEY`, `DIDIT_WORKFLOW_ID`, `DIDIT_WEBHOOK_SECRET` | Didit (workflow must include ID document, liveness, face match) |
| `XERA_KYC_ALLOW_MANUAL` | `true` keeps the old manual form open alongside providers |
| `XERA_KYC_SMILEID_COUNTRIES` | optional, see Routing |

Webhook URLs: `https://api.evoshub.xyz/api/xera/kyc/callback/smileid` and `.../callback/didit`.

## Deploy
1. Run `20261027_xera_kyc_provider_v1.sql` after `20261024_...` (additive).
2. Set env vars, deploy backend + frontend.
3. Test in each provider's **sandbox** first.

## Not verified / limits (be honest with yourself)
- Smile ID link request now follows the "Create a Smile Link" docs (multipart form, id_types, notice_privacy_policy_url...). **Still unconfirmed:** the `POST /v3/token` request/response, the `verification_method` string, the ID type names per country, and that the callback echoes our `user_id`. Test in the sandbox with one real ID before enabling.
- Smile ID's callback signature does **not** cover the body, so a result alone is never trusted: an admin must confirm in the portal.
- Smile status mapping (clear→approved, attention→in review, block/error→declined) is an assumption.
- Ghana Card / passport coverage and pricing for each provider are unconfirmed.
- The SQL has not been run on a real Postgres. Real provider calls were never made (stubbed in tests).
- Compliance: sanctioned countries are not blocked; Ghana Data Protection Act applies (privacy notice, consent, retention).
