# Manual KYC with ID photos + selfie (reviewed by an admin, erased after the decision)

## Flow
1. User presses KYC → fills name, country, ID type → uploads ID front, ID back (not needed for a passport) and a selfie → ticks the consent box.
2. Photos are shrunk and re-encoded as JPEG in the browser, then re-checked and re-encoded again on the server (proves they are real images, removes phone metadata/GPS, caps size and pixel count).
3. Files go into a **private** Supabase bucket (`xera-kyc`) under random names. There are no public or signed links.
4. The case appears for admins with the number of images. The admin opens each image through the backend. **Every view is written to `xera_kyc_access_log` (admin id, user, document, time) before the image is returned.** If the log can't be written, no image is shown.
5. **Verify is refused until that same admin has opened every uploaded image.** Admin id and time are stored on the case (`reviewed_by`, `reviewed_at`).
6. On **Verified or Failed, every image is erased** from storage and its row marked deleted (reason + time stay as proof). More-info keeps them; a resubmission erases the old ones first.
7. Images nobody reviewed are erased after `XERA_KYC_DOC_RETENTION_DAYS` (default 30) and the case goes to "more info" so the user can upload again. This runs whenever someone submits and whenever an admin opens the queue; `POST /api/admin/xera/kyc/documents/purge-expired` also does it on demand.
8. If an erase fails, the decision stands, the files stay tracked, it is logged CRITICAL and retried by the next purge.

Permanent record (no images): who verified, when, who opened which image and when, the user's consent time and notice version.

## Switch on (in this order)
1. Run `supabase/migrations/20261028_xera_kyc_documents_v1.sql` (after the 20261024 and 20261027 ones). Run its three CHECK queries: the bucket must show `public = false`, and there must be **no** policies on `storage.objects` mentioning kyc.
2. Deploy backend + frontend (`Pillow` is now listed in requirements.txt).
3. Render env: `XERA_KYC_DOC_UPLOAD=true`. Optional: `XERA_KYC_DOC_RETENTION_DAYS`, `XERA_KYC_BUCKET`, `XERA_KYC_NOTICE_VERSION`. Leave the Smile ID / Didit variables unset so this flow is the one shown. (If a provider is enabled, the provider flow wins.)
4. Test with your OWN ID and a test account first: upload, open the images as an admin, press Verify, then check in Supabase Storage that the files are gone.
5. The old text-only form closes while uploads are on (set `XERA_KYC_ALLOW_MANUAL=true` only if you want it back).

## Tested
23 + 1 backend tests (real routes, tokens, Pillow; fake database and in-memory storage): upload rules, consent, fake/oversized/decompression-bomb files, EXIF removal, no status accepted from the browser, user tokens and revoked admins refused, own-submission block, logging before viewing, no image on log failure, verify-needs-viewing, erase on Verify/Fail, erase failure + retry, expiry, resubmission. Two deliberate breakages (skip the viewing rule, skip the erase) each made tests fail. Browser-tested with a mock API: upload form, passport hides the back field, multipart sent with 3 JPEGs and no status, admin viewer, Verify locked until all images opened.

## NOT tested / limits (read these)
- The real Supabase Storage calls (`upload`, `download`, `remove`) and the SQL have **not** been run: only in-memory stand-ins. Do step 4 above before real users.
- Any active admin agent can open any pending submission. If only some staff should, tell me and I'll add a reviewer role.
- A screenshot can't be prevented. The watermark (admin id + time) and the log are deterrents and evidence, not locks.
- The server limits each file but not the total request size; put a body-size limit on your host/proxy if you can.
- I haven't checked how Supabase handles backups of deleted storage objects.
- Photos prove little without a liveness check: a staff member comparing a selfie to an ID can be fooled by edited images. This is a decision about risk, not a technical fix.

## Legal (not legal advice)
- Ghana Data Protection Act, 2012 (Act 843): register with the Data Protection Commission, publish a privacy notice that matches the consent text, name a data controller, and have a breach-response plan.
- Erasing everything at the decision is privacy-friendly, but if EVOS counts as a regulated business (e.g. under anti-money-laundering or virtual-asset rules) you may be **required to keep** ID records for a number of years. Ask a Ghanaian lawyer before launch whether deleting is allowed or whether you must retain.
- "Disciplinary and legal action" for misuse only means something if staff sign a confidentiality agreement. Do that before giving anyone admin access.
