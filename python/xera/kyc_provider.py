"""
Hybrid KYC: a verification provider checks the ID + selfie, then an admin makes the final decision.

  user picks country -> server picks the provider -> user captures ID + selfie ON THE PROVIDER'S PAGE
  -> provider's signed callback -> case becomes APPROVED / IN_REVIEW / DECLINED (provider_status)
  -> if APPROVED, an active admin checks it and presses Verify (readiness.review_kyc) -> status VERIFIED.

Rules this module enforces (the security boundary, not the UI):
  * Identity-document images and selfies never reach our servers or database.
  * No provider result sets VERIFIED. The most a callback can do is provider_status = APPROVED, which only makes
    the case eligible for the admin. (readiness.review_kyc refuses to Verify a provider case that is not APPROVED,
    and the database has the same rule as a CHECK constraint.)
  * Callbacks are authenticated by the adapters (signature + freshness), matched to a case by OUR reference (never by
    a user id the provider says), and deduplicated by event id, so a replay changes nothing.
  * A provider DECLINED moves the user to FAILED so they can try again; the user id never comes from the callback.
"""
import logging
import os
import uuid
from datetime import datetime, timezone

from main import supabase
from xera import readiness
from xera.kyc_providers import base, didit, routing, smileid

logger = logging.getLogger(__name__)

_ADAPTERS = {routing.SMILEID: smileid, routing.DIDIT: didit}
# provider_status values from which the user may (re)start a session.
_RESTARTABLE = (base.STARTED, base.ABANDONED)


class KycStartError(Exception):
    """Short machine-readable code; the route maps it to HTTP."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enabled_providers() -> list:
    return [name for name, mod in _ADAPTERS.items() if mod.enabled()]


def manual_allowed() -> bool:
    """Manual (no-provider) submissions are only allowed when no provider is enabled, or explicitly switched on."""
    return not enabled_providers() or os.getenv("XERA_KYC_ALLOW_MANUAL", "false").strip().lower() in ("1", "true", "yes", "on")


def options() -> dict:
    return {"providers_available": bool(enabled_providers()), "manual_allowed": manual_allowed()}


def _first(res):
    data = getattr(res, "data", None)
    return (data[0] if data else None) if isinstance(data, list) else (data or None)


def _row(user_id: int):
    return _first(supabase.table("xera_kyc").select("*").eq("user_id", user_id).limit(1).execute())


# ------------------------------------------------------------ start

def start(user_id: int, country_raw) -> dict:
    country = routing.normalise_country(country_raw)
    if not country:
        raise KycStartError("invalid_country")
    enabled = enabled_providers()
    if not enabled:
        raise KycStartError("provider_not_configured")

    current = readiness.get_kyc(user_id)
    if current.get("unavailable"):
        raise KycStartError("kyc_unavailable")
    row = _row(user_id)
    if current["status"] == "VERIFIED":
        raise KycStartError("kyc_already_verified")
    if current["status"] == "PENDING" and not (row and row.get("method") == "PROVIDER" and row.get("provider_status") in _RESTARTABLE):
        raise KycStartError("kyc_already_pending")       # manual case, or provider already checking / waiting for the admin

    attempt = f"xk-{int(user_id)}-{uuid.uuid4().hex}"
    session, used, last_error = None, None, None
    order = routing.provider_order(country, enabled)
    if (row and row.get("method") == "PROVIDER" and row.get("provider") == routing.SMILEID
            and row.get("provider_status") == base.DECLINED and routing.DIDIT in order):
        order = [routing.DIDIT] + [p for p in order if p != routing.DIDIT]     # Smile ID declined: second opinion
    for name in order:
        try:
            adapter = _ADAPTERS[name]
            session = adapter.create_session(attempt=attempt) if name == routing.DIDIT \
                else adapter.create_session(attempt=attempt, country=country)
            used = name
            break
        except base.KycProviderError as exc:
            last_error = str(exc)
            logger.warning("KYC provider %s could not start a session (%s)", name, exc)
    if session is None:
        raise KycStartError(last_error or "provider_unavailable")

    fields = {
        "user_id": user_id, "status": "PENDING", "method": "PROVIDER", "provider": used,
        "provider_ref": session["ref"], "provider_attempt": attempt, "provider_status": base.STARTED,
        "provider_reason": None, "provider_checked_at": None, "country": country,
        "legal_name": None, "id_type": None, "id_last4": None,
        "submitted_at": _now(), "reviewed_at": None, "reviewed_by": None, "review_note": None, "updated_at": _now(),
    }
    if row:
        supabase.table("xera_kyc").update(fields).eq("user_id", user_id).execute()
    else:
        supabase.table("xera_kyc").insert(fields).execute()
    return {"provider": used, "verification_url": session["url"]}


# ------------------------------------------------------------ callbacks

def _already_seen(provider: str, event_id: str) -> bool:
    res = supabase.table("xera_kyc_provider_events").select("event_id").eq("provider", provider).eq("event_id", event_id).limit(1).execute()
    return bool(res.data)


def _record_event(provider: str, event: dict, user_id) -> None:
    try:
        supabase.table("xera_kyc_provider_events").insert({
            "provider": provider, "event_id": event["event_id"], "user_id": user_id,
            "provider_ref": event["ref"], "status": event["status"],
        }).execute()
    except Exception as exc:     # a duplicate (unique key) is exactly the idempotency we want
        logger.info("KYC provider event not recorded (%s): %s", provider, exc)


def apply_event(provider: str, event: dict) -> dict:
    """Apply one authenticated, parsed provider event to the case it belongs to. Idempotent."""
    if _already_seen(provider, event["event_id"]):
        return {"handled": True, "duplicate": True}
    res = supabase.table("xera_kyc").select("*").eq("provider", provider).eq("provider_ref", event["ref"]).limit(1).execute()
    row = _first(res)
    # The case is found by OUR reference. A mismatched echo of our attempt id means this is not our session.
    if not row or row.get("method") != "PROVIDER" or (event.get("attempt") and event["attempt"] != row.get("provider_attempt")):
        logger.warning("KYC callback for an unknown %s reference", provider)
        return {"handled": False}
    user_id = row["user_id"]
    if row.get("status") == "VERIFIED":
        _record_event(provider, event, user_id)
        return {"handled": True, "ignored": "already_verified"}

    new, current = event["status"], row.get("provider_status")
    if new == base.STARTED and current in (base.APPROVED, base.IN_REVIEW, base.DECLINED):
        _record_event(provider, event, user_id)
        return {"handled": True, "ignored": "stale"}      # an earlier/less final state arriving late

    patch = {"provider_status": new, "provider_reason": event.get("reason"),
             "provider_checked_at": _now(), "updated_at": _now()}
    note_key = f"kyc_provider:{provider}:{row.get('provider_ref')}:{new}"
    if new == base.DECLINED:
        patch.update(status="FAILED", review_note="We couldn't verify your documents. Please try again with a clear photo of your ID and a good selfie.")
        readiness.notify(user_id, "kyc_failed", "Verification unsuccessful",
                         "We couldn't verify your documents. You can try again.", dedupe_key=note_key)
    elif new == base.APPROVED:
        patch.update(status="PENDING", review_note=None)      # NEVER VERIFIED here: waits for the admin
        readiness.notify(user_id, "kyc_provider_approved", "Documents checked",
                         "Your documents passed the automatic check. A team member will confirm shortly.", dedupe_key=note_key)
    elif new == base.IN_REVIEW:
        patch.update(status="PENDING")
    supabase.table("xera_kyc").update(patch).eq("user_id", user_id).execute()
    _record_event(provider, event, user_id)
    return {"handled": True, "status": new}


def handle_callback(provider: str, raw_body: bytes, headers) -> dict:
    adapter = _ADAPTERS.get(provider)
    if adapter is None or not adapter.enabled():
        raise base.KycWebhookError("provider_not_enabled")
    payload = adapter.verify_webhook(raw_body, headers)         # raises KycWebhookError on a bad signature
    event = adapter.parse_event(payload)
    if event is None:
        return {"handled": False}
    return apply_event(provider, event)
