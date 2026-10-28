"""
Smile ID adapter (African countries).

CONFIRMED from Smile ID's docs:
  * Callbacks: POST JSON with headers Response-Signature (base64 HMAC-SHA256), Response-Timestamp (ISO 8601),
    smileid-job-id, user-id. Signature = base64( HMAC_SHA256(key = API key, msg = timestamp + partner_id + "sid_request") ).
    NOTE: that message does NOT include the body, so the signature proves the call came from Smile ID's signer but
    does not by itself prove the body is untouched. That is why a Smile result can only make a case APPROVED
    (waiting for the admin, who checks the result in the Smile ID portal), never VERIFIED.
  * Result body: {"status": "clear" | "attention" | "block" | "error", "message", "reason",
                  "partner_params": {"job_id", "user_id", "job_type"}}. "clear" = success.
  * Environments: sandbox https://testapi.smileidentity.com, production https://api.smileidentity.com.
  * Auth for API calls: POST /v3/token with partner_id + api_key; then SmileID-Token + SmileID-Partner-ID headers.
  * Smile Links: POST /v3/smile_links creates a hosted link; single-use links accept a user_id, results go to the
    callback URL, callback/redirect/privacy/logo URLs must be public https.

CONFIRMED from the "Create a Smile Link" page (v3): POST {base}/v3/smile_links, header SmileID-Token, body is
multipart/form-data (NOT JSON) with id_types (JSON-encoded array of {country, id_type, verification_method}, min 1),
notice_privacy_policy_url, is_single_use, callback_url, user_id (unique per link), redirect_url, logo_url,
partner_params (JSON). Response 201 {"link", "ref_id", "user_id"}. An unsupported country/ID/method combination returns 400.
The redirect back to us can be forged by the user, so the outcome comes ONLY from the signed callback.

STILL UNCONFIRMED (verify in the sandbox before enabling): the POST /v3/token request/response (field "token"),
the exact verification_method string for ID + selfie (SMILEID_VERIFICATION_METHOD, default "document_verification"),
the ID type names per country (SMILEID_ID_TYPES, from Smile ID's ID Coverage page), and that the callback echoes our
user_id in partner_params.user_id. A country with no configured ID types is reported as unsupported, so the user is
sent to the fallback provider instead.

Environment: SMILEID_PARTNER_ID, SMILEID_API_KEY, SMILEID_ENV (sandbox|production, default sandbox),
SMILEID_CALLBACK_URL (https://<api>/api/xera/kyc/callback/smileid), SMILEID_PRIVACY_POLICY_URL,
optional SMILEID_REDIRECT_URL and SMILEID_LOGO_URL, XERA_KYC_SMILEID_ENABLED=true,
SMILEID_ID_TYPES='{"GH": ["PASSPORT", "..."], "*": ["PASSPORT"]}' (country -> ID type names; "*" = any other country),
SMILEID_VERIFICATION_METHOD (default document_verification).
"""
import base64
import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone

import httpx

from xera.kyc_providers import base

logger = logging.getLogger(__name__)

NAME = "smileid"
_MAX_CALLBACK_AGE_SECONDS = 3600


def _base_url() -> str:
    return "https://api.smileidentity.com" if os.getenv("SMILEID_ENV", "sandbox").strip().lower() == "production" \
        else "https://testapi.smileidentity.com"


def enabled() -> bool:
    on = os.getenv("XERA_KYC_SMILEID_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    need = ("SMILEID_PARTNER_ID", "SMILEID_API_KEY", "SMILEID_CALLBACK_URL", "SMILEID_PRIVACY_POLICY_URL")
    return on and all(os.getenv(k, "").strip() for k in need)


def _token() -> str:
    partner_id, api_key = os.getenv("SMILEID_PARTNER_ID", "").strip(), os.getenv("SMILEID_API_KEY", "").strip()
    try:
        resp = httpx.post(f"{_base_url()}/v3/token", timeout=15, headers={"partner_id": partner_id, "api_key": api_key})
    except httpx.HTTPError:
        raise base.KycProviderError("provider_unreachable")
    if resp.status_code != 200:
        logger.error("Smile ID token request refused: HTTP %s", resp.status_code)
        raise base.KycProviderError("provider_refused")
    try:
        return str(resp.json()["token"])          # UNCONFIRMED field name: check in the sandbox
    except (ValueError, KeyError, TypeError):
        raise base.KycProviderError("provider_bad_response")


def _id_types_for(country: str) -> list:
    """ID types offered for a country, from config. Empty -> not supported here (caller falls back)."""
    import json
    try:
        table = json.loads(os.getenv("SMILEID_ID_TYPES", "") or "{}")
    except ValueError:
        logger.error("SMILEID_ID_TYPES is not valid JSON")
        return []
    names = table.get(country) or table.get("*") or []
    method = os.getenv("SMILEID_VERIFICATION_METHOD", "document_verification").strip()
    return [{"country": country, "id_type": str(n).strip().upper(), "verification_method": method}
            for n in names if str(n).strip()]


def _link_fields(*, attempt: str, country: str) -> dict:
    """multipart/form-data text fields (all strings)."""
    import json
    id_types = _id_types_for(country)
    if not id_types:
        raise base.KycProviderError("country_not_supported")
    fields = {
        "id_types": json.dumps(id_types),
        "name": "XERA identity check",
        "notice_privacy_policy_url": os.getenv("SMILEID_PRIVACY_POLICY_URL", "").strip(),
        "is_single_use": "true",
        "callback_url": os.getenv("SMILEID_CALLBACK_URL", "").strip(),
        "user_id": attempt,                       # OUR reference; expected back in the callback
        "partner_params": json.dumps({"user_id": attempt}),
    }
    if os.getenv("SMILEID_REDIRECT_URL", "").strip():
        fields["redirect_url"] = os.getenv("SMILEID_REDIRECT_URL").strip()
    if os.getenv("SMILEID_LOGO_URL", "").strip():
        fields["logo_url"] = os.getenv("SMILEID_LOGO_URL").strip()
    return fields


def create_session(*, attempt: str, country: str) -> dict:
    """Start a hosted verification. Returns {"ref": attempt (what the callback echoes back), "url": link}."""
    fields = _link_fields(attempt=attempt, country=country)      # may raise country_not_supported before any call
    token = _token()
    try:
        # (None, value) tuples make httpx send multipart/form-data without any file.
        resp = httpx.post(f"{_base_url()}/v3/smile_links", files={k: (None, v) for k, v in fields.items()}, timeout=15,
                          headers={"SmileID-Token": token})
    except httpx.HTTPError:
        raise base.KycProviderError("provider_unreachable")
    if resp.status_code == 400:
        raise base.KycProviderError("country_not_supported")      # e.g. "NG PASSPORT is not supported for ..."
    if resp.status_code not in (200, 201):
        logger.error("Smile ID create link refused: HTTP %s", resp.status_code)
        raise base.KycProviderError("provider_refused")
    try:
        url = resp.json().get("link")
        if not url:
            raise KeyError("link")
        return {"ref": attempt, "url": str(url)}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise base.KycProviderError("provider_bad_response")


def _parse_ts(value):
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def verify_webhook(raw_body: bytes, headers) -> dict:
    import json
    api_key, partner_id = os.getenv("SMILEID_API_KEY", "").strip(), os.getenv("SMILEID_PARTNER_ID", "").strip()
    if not api_key or not partner_id:
        raise base.KycWebhookError("webhook_not_configured")     # fail closed
    get = lambda name: headers.get(name) or headers.get(name.lower())   # noqa: E731
    timestamp, signature = get("Response-Timestamp"), get("Response-Signature")
    if not timestamp or not signature:
        raise base.KycWebhookError("missing_signature")
    expected = base64.b64encode(hmac.new(api_key.encode(), f"{timestamp}{partner_id}sid_request".encode(), hashlib.sha256).digest()).decode()
    if not hmac.compare_digest(str(signature), expected):
        raise base.KycWebhookError("bad_signature")
    ts = _parse_ts(timestamp)
    if ts is None or abs((datetime.now(timezone.utc) - ts).total_seconds()) > _MAX_CALLBACK_AGE_SECONDS:
        raise base.KycWebhookError("stale_timestamp")            # limits replay of a captured signature
    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise base.KycWebhookError("bad_body")
    if not isinstance(payload, dict):
        raise base.KycWebhookError("bad_body")
    payload["_job_id"] = get("smileid-job-id") or ""
    return payload


def parse_event(payload: dict):
    params = payload.get("partner_params") or {}
    attempt = params.get("user_id")
    if not attempt:
        return None
    raw = str(payload.get("status", "")).lower()
    status = base.APPROVED if raw == "clear" else base.IN_REVIEW if raw == "attention" else base.DECLINED
    job = payload.get("_job_id") or params.get("job_id") or ""
    return {"event_id": f"{job}:{raw}", "ref": str(attempt), "attempt": str(attempt), "status": status,
            "reason": (str(payload.get("reason") or "")[:120] or None)}
