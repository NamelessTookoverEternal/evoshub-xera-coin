"""
Didit adapter (global provider).

Documented behaviour used here (docs.didit.me, "Create session" + "Webhooks"):
  * POST https://verification.didit.me/v3/session/   header x-api-key   body {workflow_id, vendor_data, callback, metadata}
    -> 201 {session_id, url, status:"Not Started", ...}; the user is sent to `url`.
  * Webhook POST (JSON) with headers X-Signature-V2 (+ X-Timestamp). X-Signature-V2 = hex HMAC-SHA256 over the
    body re-serialised as compact JSON with recursively SORTED keys, unicode not escaped, whole-number floats
    written as integers; key = the webhook secret. Reject when |now - X-Timestamp| > 300 s. During the 24 h after
    a secret rotation the old signature arrives in X-Signature-V2-Previous.
  * Event `status.updated` carries session_id, status (Approved | Declined | In Review | In Progress | Not Started |
    Abandoned | Expired | Kyc Expired | Resubmitted | Awaiting User), vendor_data, and a stable event_id.

Environment: DIDIT_API_KEY, DIDIT_WORKFLOW_ID (a KYC workflow with ID document + liveness + face match),
DIDIT_WEBHOOK_SECRET, optional DIDIT_CALLBACK_URL (where the user returns), XERA_KYC_DIDIT_ENABLED=true.
"""
import hashlib
import hmac
import json
import logging
import os
import time

import httpx

from xera.kyc_providers import base

logger = logging.getLogger(__name__)

NAME = "didit"
_SESSION_URL = "https://verification.didit.me/v3/session/"

_STATUS_MAP = {
    "Approved": base.APPROVED,
    "Declined": base.DECLINED,
    "In Review": base.IN_REVIEW,
    "Abandoned": base.ABANDONED,
    "Expired": base.ABANDONED,
    "Kyc Expired": base.ABANDONED,
    "In Progress": base.STARTED,
    "Not Started": base.STARTED,
    "Awaiting User": base.STARTED,
    "Resubmitted": base.STARTED,
}


def enabled() -> bool:
    on = os.getenv("XERA_KYC_DIDIT_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    return on and all(os.getenv(k, "").strip() for k in ("DIDIT_API_KEY", "DIDIT_WORKFLOW_ID", "DIDIT_WEBHOOK_SECRET"))


def create_session(*, attempt: str) -> dict:
    """Start a hosted verification for one attempt. Returns {"ref": session_id, "url": hosted page}."""
    body = {"workflow_id": os.getenv("DIDIT_WORKFLOW_ID", "").strip(), "vendor_data": attempt,
            "metadata": {"product": "xera_kyc"}}
    callback = os.getenv("DIDIT_CALLBACK_URL", "").strip()
    if callback:
        body["callback"] = callback
    try:
        resp = httpx.post(_SESSION_URL, json=body, timeout=15,
                          headers={"x-api-key": os.getenv("DIDIT_API_KEY", "").strip(), "Content-Type": "application/json"})
    except httpx.HTTPError:
        raise base.KycProviderError("provider_unreachable")
    if resp.status_code != 201:
        logger.error("Didit create session refused: HTTP %s", resp.status_code)   # body may echo input: not logged
        raise base.KycProviderError("provider_refused")
    try:
        data = resp.json()
        return {"ref": str(data["session_id"]), "url": str(data["url"])}
    except (ValueError, KeyError, TypeError):
        raise base.KycProviderError("provider_bad_response")


def _normalise(value):
    """Match Didit's canonicalisation: whole-number floats become integers (recursively)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items()}
    return value


def _signature_v2(parsed, secret: str) -> str:
    canonical = json.dumps(_normalise(parsed), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def verify_webhook(raw_body: bytes, headers) -> dict:
    """Authenticate a Didit callback and return the parsed body. Raises KycWebhookError otherwise."""
    secret = os.getenv("DIDIT_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise base.KycWebhookError("webhook_not_configured")     # fail closed
    get = lambda name: headers.get(name) or headers.get(name.lower())   # noqa: E731
    try:
        ts = int(get("X-Timestamp"))
    except (TypeError, ValueError):
        raise base.KycWebhookError("bad_timestamp")
    if abs(time.time() - ts) > 300:
        raise base.KycWebhookError("stale_timestamp")
    try:
        parsed = json.loads(raw_body)
    except ValueError:
        raise base.KycWebhookError("bad_body")
    expected = _signature_v2(parsed, secret)
    candidates = [get("X-Signature-V2"), get("X-Signature-V2-Previous")]
    if not any(c and hmac.compare_digest(str(c), expected) for c in candidates):
        raise base.KycWebhookError("bad_signature")
    return parsed


def parse_event(payload: dict):
    """-> {"event_id","ref","attempt","status","reason"} for a session status event, else None."""
    if payload.get("webhook_type") != "status.updated":
        return None
    status = _STATUS_MAP.get(payload.get("status"))
    if not status or not payload.get("session_id"):
        return None
    event_id = payload.get("event_id") or f"{payload['session_id']}:{payload.get('status')}"
    return {"event_id": str(event_id), "ref": str(payload["session_id"]),
            "attempt": payload.get("vendor_data"), "status": status, "reason": None}
