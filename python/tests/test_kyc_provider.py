"""
Hybrid KYC: provider (Smile ID for African countries, Didit elsewhere) + admin final decision.

Real routes, real user/admin tokens, real callback signing; Supabase is the in-memory fake and the providers'
HTTP APIs are stubbed (nothing is ever sent to Smile ID or Didit). Not covered here: the providers' real
sandboxes and the SQL itself (see the setup notes).
"""
import base64
import hashlib
import hmac
import importlib
import json
import time
import types
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

DIDIT_SECRET = "didit-whsec"
SMILE_KEY, SMILE_PARTNER = "smile-api-key", "9999"


def _mod(name):
    return importlib.import_module(name)


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._d = status, data

    def json(self):
        return self._d


@pytest.fixture
def api(fake_supabase, monkeypatch):
    for k, v in {"XERA_TOKEN_SECRET": "user-secret", "ADMIN_TOKEN_SECRET": "admin-secret",
                 "XERA_KYC_DIDIT_ENABLED": "true", "DIDIT_API_KEY": "dk", "DIDIT_WORKFLOW_ID": "wf-1",
                 "DIDIT_WEBHOOK_SECRET": DIDIT_SECRET,
                 "XERA_KYC_SMILEID_ENABLED": "true", "SMILEID_PARTNER_ID": SMILE_PARTNER, "SMILEID_API_KEY": SMILE_KEY,
                 "SMILEID_CALLBACK_URL": "https://api.example/api/xera/kyc/callback/smileid",
                 "SMILEID_PRIVACY_POLICY_URL": "https://example/privacy",
                 "SMILEID_ID_TYPES": json.dumps({"GH": ["passport", "GHANA_CARD"], "*": ["PASSPORT"]})}.items():
        monkeypatch.setenv(k, v)
    for k in ("XERA_KYC_ALLOW_MANUAL", "XERA_KYC_SMILEID_COUNTRIES"):
        monkeypatch.delenv(k, raising=False)
    rr, ua, aa = _mod("xera.routes_readiness"), _mod("xera.user_auth"), _mod("xera.admin_auth")
    didit = _mod("xera.kyc_providers.didit")

    calls = {"didit": [], "smile": [], "smile_status": 200, "didit_status": 201}

    def fake_post(url, **kw):                      # didit and smileid share the one httpx module: dispatch by URL
        if "didit.me" in url:
            calls["didit"].append(kw["json"])
            n = len(calls["didit"])
            return _Resp(calls["didit_status"], {"session_id": f"sess-{n}", "url": f"https://verify.didit.me/session/{n}", "status": "Not Started"})
        if url.endswith("/v3/token"):
            return _Resp(200, {"token": "tok"})
        calls["smile"].append({k: v[1] for k, v in kw["files"].items()})      # multipart text fields
        return _Resp(calls["smile_status"], {"link": "https://links.smileidentity.com/abc"})

    monkeypatch.setattr(didit.httpx, "post", fake_post)

    app = FastAPI()
    app.include_router(rr.router, prefix="/api/xera")
    app.include_router(rr.admin_router, prefix="/api/admin/xera")
    fake_supabase.store["admin_agents"] = [{"user_id": 7, "is_active": True}, {"user_id": 9, "is_active": False}]
    fake_supabase.store["users"] = [{"id": i} for i in (1, 2, 7)]
    return types.SimpleNamespace(
        client=TestClient(app), fake=fake_supabase, calls=calls, monkeypatch=monkeypatch,
        h=lambda uid: {"Authorization": f"Bearer {ua.make_user_token(uid)}"},
        a=lambda uid: {"Authorization": f"Bearer {aa.make_admin_token(uid)}"},
    )


def _row(api, uid=1):
    return next((r for r in api.fake.store.get("xera_kyc", []) if r["user_id"] == uid), None)


def _start_didit(api, uid=1):
    api.monkeypatch.setenv("XERA_KYC_SMILEID_ENABLED", "false")
    r = _start(api, "US", uid)
    api.monkeypatch.setenv("XERA_KYC_SMILEID_ENABLED", "true")
    return r


def _start(api, country, uid=1):
    return api.client.post("/api/xera/kyc/start", headers=api.h(uid), json={"country": country})


# ---------------------------------------------------------------- callbacks (signed like the providers do)
def _didit_cb(api, body, *, secret=DIDIT_SECRET, ts=None, path="didit"):
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    headers = {"X-Signature-V2": sig, "X-Timestamp": str(int(ts if ts is not None else time.time())), "Content-Type": "application/json"}
    return api.client.post(f"/api/xera/kyc/callback/{path}", content=json.dumps(body), headers=headers)


def _didit_event(session="sess-1", status="Approved", attempt=None, event_id="ev-1"):
    row = next(iter(r for r in [] ), None)
    return {"webhook_type": "status.updated", "event_id": event_id, "session_id": session, "status": status,
            "vendor_data": attempt, "environment": "sandbox"}


def _smile_cb(api, status, attempt, *, key=SMILE_KEY, ts=None, job="job-1"):
    ts = ts or datetime.now(timezone.utc).isoformat()
    sig = base64.b64encode(hmac.new(key.encode(), f"{ts}{SMILE_PARTNER}sid_request".encode(), hashlib.sha256).digest()).decode()
    body = {"status": status, "message": "m", "reason": None, "partner_params": {"job_id": job, "user_id": attempt, "job_type": 6}}
    return api.client.post("/api/xera/kyc/callback/smileid", content=json.dumps(body), headers={
        "Response-Signature": sig, "Response-Timestamp": ts, "smileid-job-id": job, "Content-Type": "application/json"})


# ================================================================ routing
def test_smile_id_is_first_for_every_country_and_didit_is_the_fallback():
    r = _mod("xera.kyc_providers.routing")
    for cc in ("GH", "NG", "US", "GB", "IN", "BR", "AE"):
        assert r.preferred_provider(cc) == "smileid", cc
    assert r.provider_order("US", ["smileid", "didit"]) == ["smileid", "didit"]
    assert r.provider_order("US", ["didit"]) == ["didit"]                      # Smile ID off -> Didit
    assert r.normalise_country(" gh ") == "GH" and r.normalise_country("Ghana") == "" and r.normalise_country("G1") == ""


def test_the_smile_id_first_list_can_be_restricted_by_config(api):
    api.monkeypatch.setenv("XERA_KYC_SMILEID_COUNTRIES", "GH,NG")
    r = _mod("xera.kyc_providers.routing")
    assert r.preferred_provider("US") == "didit" and r.preferred_provider("GH") == "smileid"


# ================================================================ starting
def test_ghana_user_is_sent_to_smile_id_and_a_pending_provider_case_is_created(api):
    r = _start(api, "GH")
    assert r.status_code == 200 and r.json()["provider"] == "smileid"
    assert r.json()["verification_url"].startswith("https://links.smileidentity.com/")
    row = _row(api)
    assert (row["status"], row["method"], row["provider"], row["provider_status"], row["country"]) == ("PENDING", "PROVIDER", "smileid", "STARTED", "GH")
    sent = api.calls["smile"][0]
    assert sent["user_id"] == row["provider_attempt"] and row["provider_attempt"].startswith("xk-1-")   # OUR reference
    assert json.loads(sent["id_types"]) == [{"country": "GH", "id_type": "PASSPORT", "verification_method": "document_verification"},
                                           {"country": "GH", "id_type": "GHANA_CARD", "verification_method": "document_verification"}]
    assert sent["is_single_use"] == "true" and sent["notice_privacy_policy_url"] == "https://example/privacy"
    assert sent["callback_url"].startswith("https://") and "status" not in sent and "image" not in sent
    assert not api.calls["didit"]


def test_us_user_is_sent_to_didit_when_smile_id_is_off(api):
    api.monkeypatch.setenv("XERA_KYC_SMILEID_ENABLED", "false")
    r = _start(api, "us")
    assert r.status_code == 200 and r.json()["provider"] == "didit" and r.json()["verification_url"] == "https://verify.didit.me/session/1"
    row = _row(api)
    assert row["provider"] == "didit" and row["provider_ref"] == "sess-1"
    assert api.calls["didit"][0]["vendor_data"] == row["provider_attempt"] and api.calls["didit"][0]["workflow_id"] == "wf-1"
    assert not api.calls["smile"]


def test_the_browser_cannot_choose_the_provider_or_set_a_status(api):
    for body in ({"country": "US", "provider": "smileid"}, {"country": "US", "status": "VERIFIED"}, {"country": "US", "image": "x"}, {}):
        assert _start_body(api, body).status_code == 422
    assert _row(api) is None
    assert api.client.post("/api/xera/kyc/start", json={"country": "US"}).status_code == 401


def _start_body(api, body, uid=1):
    return api.client.post("/api/xera/kyc/start", headers=api.h(uid), json=body)


def test_bad_country_is_refused(api):
    assert _start(api, "Ghana").status_code == 422          # not a 2-letter code
    assert _start(api, "G1").status_code == 400


def test_no_provider_configured_means_a_clear_503_and_manual_still_works(api):
    api.monkeypatch.setenv("XERA_KYC_DIDIT_ENABLED", "false")
    api.monkeypatch.setenv("XERA_KYC_SMILEID_ENABLED", "false")
    assert _start(api, "GH").status_code == 503
    r = api.client.post("/api/xera/kyc/submit", headers=api.h(1), json={"legal_name": "Ama Mensah", "country": "GH", "id_type": "passport", "id_number": "G1234567"})
    assert r.status_code == 200 and _row(api)["method"] == "MANUAL"


def test_manual_form_is_closed_while_a_provider_is_on(api):
    r = api.client.post("/api/xera/kyc/submit", headers=api.h(1), json={"legal_name": "Ama Mensah", "country": "GH", "id_type": "passport", "id_number": "G1234567"})
    assert r.status_code == 409 and _row(api) is None
    api.monkeypatch.setenv("XERA_KYC_ALLOW_MANUAL", "true")
    assert api.client.post("/api/xera/kyc/submit", headers=api.h(1), json={"legal_name": "Ama Mensah", "country": "GH", "id_type": "passport", "id_number": "G1234567"}).status_code == 200


def test_unsupported_country_for_smile_id_falls_back_to_didit_or_reports_it(api):
    api.calls["smile_status"] = 400
    r = _start(api, "NG")
    assert r.status_code == 200 and r.json()["provider"] == "didit"
    api.fake.store["xera_kyc"].clear()
    api.monkeypatch.setenv("XERA_KYC_DIDIT_ENABLED", "false")
    r = _start(api, "NG")
    assert r.status_code == 400 and "isn't available for that country" in r.json()["detail"]
    assert _row(api) is None                                  # nothing half-created


def test_a_started_case_can_be_restarted_but_a_checked_one_cannot(api):
    _start_didit(api)
    again = _start_didit(api)
    assert again.status_code == 200 and _row(api)["provider_ref"] == "sess-2"
    _row(api)["provider_status"] = "APPROVED"
    assert _start_didit(api).status_code == 409                # waiting for the admin
    _row(api)["provider_status"] = "IN_REVIEW"
    assert _start_didit(api).status_code == 409
    _row(api).update(status="VERIFIED", reviewed_by=7)
    assert _start_didit(api).status_code == 409


def test_a_failed_case_can_start_again(api):
    _start_didit(api)
    _row(api).update(status="FAILED", provider_status="DECLINED")
    assert _start_didit(api).status_code == 200 and _row(api)["status"] == "PENDING" and _row(api)["provider_status"] == "STARTED"


def test_provider_outage_creates_nothing(api):
    api.monkeypatch.setenv("XERA_KYC_SMILEID_ENABLED", "false")
    api.calls["didit_status"] = 500
    assert _start_didit(api).status_code == 502 and _row(api) is None


# ================================================================ callbacks: Didit
def test_didit_approval_waits_for_the_admin_it_is_never_verified(api):
    _start_didit(api)
    att = _row(api)["provider_attempt"]
    r = _didit_cb(api, _didit_event(attempt=att))
    assert r.status_code == 200
    row = _row(api)
    assert row["provider_status"] == "APPROVED" and row["status"] == "PENDING"
    assert row["reviewed_by"] is None
    kyc = api.client.get("/api/xera/readiness", headers=api.h(1)).json()
    assert kyc["kyc"]["status"] == "PENDING" and kyc["kyc"]["provider_status"] == "APPROVED"
    assert "kyc_not_verified" in kyc["missing"]                 # the transfer gate still blocks
    assert any(n["kind"] == "kyc_provider_approved" for n in api.fake.store["xera_notifications"])


@pytest.mark.parametrize("make", ["bad_secret", "stale", "no_headers", "tampered"])
def test_didit_callbacks_that_fail_authentication_change_nothing(api, make):
    _start_didit(api)
    att = _row(api)["provider_attempt"]
    ev = _didit_event(attempt=att)
    if make == "bad_secret":
        r = _didit_cb(api, ev, secret="not-the-secret")
    elif make == "stale":
        r = _didit_cb(api, ev, ts=time.time() - 3600)
    elif make == "no_headers":
        r = api.client.post("/api/xera/kyc/callback/didit", content=json.dumps(ev))
    else:   # signed for Declined, delivered as Approved
        canonical = json.dumps({**ev, "status": "Declined"}, sort_keys=True, separators=(",", ":"))
        sig = hmac.new(DIDIT_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        r = api.client.post("/api/xera/kyc/callback/didit", content=json.dumps(ev), headers={"X-Signature-V2": sig, "X-Timestamp": str(int(time.time()))})
    assert r.status_code == 401
    assert _row(api)["provider_status"] == "STARTED" and _row(api)["status"] == "PENDING"


def test_didit_callbacks_fail_closed_without_a_secret(api):
    _start_didit(api)
    api.monkeypatch.delenv("DIDIT_WEBHOOK_SECRET")
    assert _didit_cb(api, _didit_event(attempt=_row(api)["provider_attempt"])).status_code == 401


def test_a_replayed_didit_event_applies_once(api):
    _start_didit(api)
    ev = _didit_event(attempt=_row(api)["provider_attempt"])
    assert _didit_cb(api, ev).json().get("duplicate") is None
    assert _didit_cb(api, ev).json().get("duplicate") is True
    assert len([n for n in api.fake.store["xera_notifications"] if n["kind"] == "kyc_provider_approved"]) == 1
    assert len(api.fake.store["xera_kyc_provider_events"]) == 1


def test_didit_decline_fails_the_case_and_the_user_can_retry(api):
    _start_didit(api)
    assert _didit_cb(api, _didit_event(status="Declined", attempt=_row(api)["provider_attempt"])).status_code == 200
    assert (_row(api)["status"], _row(api)["provider_status"]) == ("FAILED", "DECLINED")
    assert any(n["kind"] == "kyc_failed" for n in api.fake.store["xera_notifications"])
    assert _start_didit(api).status_code == 200


def test_in_review_and_abandoned_are_recorded_without_deciding(api):
    _start_didit(api)
    att = _row(api)["provider_attempt"]
    _didit_cb(api, _didit_event(status="In Review", attempt=att, event_id="e1"))
    assert (_row(api)["status"], _row(api)["provider_status"]) == ("PENDING", "IN_REVIEW")
    _didit_cb(api, _didit_event(status="In Progress", attempt=att, event_id="e2"))   # late, less final: ignored
    assert _row(api)["provider_status"] == "IN_REVIEW"


def test_unknown_or_foreign_sessions_are_ignored(api):
    _start_didit(api)
    r = _didit_cb(api, _didit_event(session="someone-elses", attempt="xk-2-abc"))
    assert r.status_code == 200 and r.json()["handled"] is False
    assert _row(api)["provider_status"] == "STARTED"
    # right session id but a vendor_data that is not OUR attempt reference
    r = _didit_cb(api, _didit_event(session="sess-1", attempt="xk-2-forged", event_id="ev-2"))
    assert r.json()["handled"] is False and _row(api)["provider_status"] == "STARTED"


def test_callback_cannot_name_a_user_or_touch_a_verified_case(api):
    _start_didit(api)
    att = _row(api)["provider_attempt"]
    _row(api).update(status="VERIFIED", reviewed_by=7, provider_status="APPROVED")
    _didit_cb(api, {**_didit_event(status="Declined", attempt=att), "user_id": 2, "vendor_user_id": "2"})
    assert (_row(api)["status"], _row(api)["provider_status"]) == ("VERIFIED", "APPROVED")
    assert _row(api, 2) is None


def test_unknown_provider_path_and_disabled_provider_are_rejected(api):
    assert api.client.post("/api/xera/kyc/callback/nope", content="{}").status_code == 401
    api.monkeypatch.setenv("XERA_KYC_DIDIT_ENABLED", "false")
    assert _didit_cb(api, _didit_event()).status_code == 401


# ================================================================ callbacks: Smile ID
@pytest.mark.parametrize("raw,provider_status,user_status", [("clear", "APPROVED", "PENDING"), ("attention", "IN_REVIEW", "PENDING"),
                                                             ("block", "DECLINED", "FAILED"), ("error", "DECLINED", "FAILED")])
def test_smile_id_results_map_safely(api, raw, provider_status, user_status):
    _start(api, "GH")
    assert _smile_cb(api, raw, _row(api)["provider_attempt"]).status_code == 200
    assert (_row(api)["provider_status"], _row(api)["status"]) == (provider_status, user_status)
    assert _row(api)["reviewed_by"] is None                   # a provider result is never a verification


def test_smile_id_bad_signature_or_old_timestamp_changes_nothing(api):
    _start(api, "GH")
    att = _row(api)["provider_attempt"]
    assert _smile_cb(api, "clear", att, key="wrong").status_code == 401
    assert _smile_cb(api, "clear", att, ts="2020-01-01T00:00:00+00:00").status_code == 401
    assert _row(api)["provider_status"] == "STARTED"


def test_smile_id_replay_applies_once_and_unknown_attempts_are_ignored(api):
    _start(api, "GH")
    att = _row(api)["provider_attempt"]
    _smile_cb(api, "clear", att)
    assert _smile_cb(api, "clear", att).json().get("duplicate") is True
    assert _smile_cb(api, "clear", "xk-2-unknown", job="job-9").json()["handled"] is False


# ================================================================ admin: the human decision
def _review(api, uid, decision, note="", admin=7):
    return api.client.post(f"/api/admin/xera/kyc/{uid}/review", headers=api.a(admin), json={"decision": decision, "note": note})


def test_admin_cannot_verify_before_the_provider_approved(api):
    _start_didit(api)
    r = _review(api, 1, "VERIFIED")
    assert r.status_code == 409 and "provider" in r.json()["detail"].lower()
    assert _row(api)["status"] == "PENDING"
    _didit_cb(api, _didit_event(status="In Review", attempt=_row(api)["provider_attempt"]))
    assert _review(api, 1, "VERIFIED").status_code == 409


def test_after_the_provider_approves_the_admin_can_verify_and_the_user_sees_it(api):
    _start_didit(api)
    _didit_cb(api, _didit_event(attempt=_row(api)["provider_attempt"]))
    r = _review(api, 1, "VERIFIED")
    assert r.status_code == 200
    row = _row(api)
    assert (row["status"], row["reviewed_by"], row["provider_status"]) == ("VERIFIED", 7, "APPROVED")
    assert api.client.get("/api/xera/readiness", headers=api.h(1)).json()["kyc"]["status"] == "VERIFIED"
    assert any(n["kind"] == "kyc_verified" for n in api.fake.store["xera_notifications"])


def test_admin_can_still_fail_or_ask_for_more_info_at_any_stage(api):
    _start_didit(api)
    assert _review(api, 1, "INFO_REQUIRED", "Photo is blurry").status_code == 200
    assert _row(api)["status"] == "INFO_REQUIRED"


def test_only_an_active_admin_can_review_and_never_themselves(api):
    _start_didit(api)
    _didit_cb(api, _didit_event(attempt=_row(api)["provider_attempt"]))
    assert api.client.post("/api/admin/xera/kyc/1/review", headers=api.h(1), json={"decision": "VERIFIED"}).status_code == 401
    assert _review(api, 1, "VERIFIED", admin=9).status_code == 403          # revoked admin
    assert api.client.post("/api/admin/xera/kyc/1/review", json={"decision": "VERIFIED"}).status_code == 401
    assert _row(api)["status"] == "PENDING"


def test_admin_queue_shows_the_provider_result_but_no_images_or_secrets(api):
    _start_didit(api)
    _didit_cb(api, _didit_event(attempt=_row(api)["provider_attempt"]))
    items = api.client.get("/api/admin/xera/kyc?status=PENDING", headers=api.a(7)).json()["items"]
    assert items[0]["provider"] == "didit" and items[0]["provider_status"] == "APPROVED" and items[0]["provider_ref"] == "sess-1"
    assert not any(k in items[0] for k in ("image", "selfie", "document", "id_number", "api_key"))


def test_options_are_reported_to_the_dashboard(api):
    o = api.client.get("/api/xera/readiness", headers=api.h(1)).json()["kyc_options"]
    assert o["providers_available"] is True and o["manual_allowed"] is False and o["upload_enabled"] is False


# ================================================================ Smile ID first, rejected cases surface to the admin
def test_a_smile_id_rejection_appears_in_the_admin_queue_and_the_retry_goes_to_didit(api):
    assert _start(api, "US").json()["provider"] == "smileid"            # even a non-African user starts with Smile ID
    _smile_cb(api, "block", _row(api)["provider_attempt"])
    assert (_row(api)["status"], _row(api)["provider_status"]) == ("FAILED", "DECLINED")

    q = api.client.get("/api/admin/xera/kyc?status=PROVIDER_DECLINED", headers=api.a(7)).json()
    assert [i["user_id"] for i in q["items"]] == [1] and q["items"][0]["provider"] == "smileid"
    assert api.client.get("/api/admin/xera/kyc?status=PENDING", headers=api.a(7)).json()["provider_declined_count"] == 1

    again = _start(api, "US")                                            # second opinion
    assert again.json()["provider"] == "didit" and _row(api)["provider"] == "didit"
    assert api.client.get("/api/admin/xera/kyc?status=PROVIDER_DECLINED", headers=api.a(7)).json()["items"] == []


def test_a_rejected_case_cannot_be_verified_by_the_admin(api):
    _start(api, "GH")
    _smile_cb(api, "block", _row(api)["provider_attempt"])
    assert _review(api, 1, "VERIFIED").status_code == 409
    assert _row(api)["status"] == "FAILED"


def test_only_admins_can_see_the_declined_queue(api):
    assert api.client.get("/api/admin/xera/kyc?status=PROVIDER_DECLINED", headers=api.h(1)).status_code == 401


def test_a_country_with_no_configured_id_types_falls_back_to_didit_without_calling_smile_id(api):
    api.monkeypatch.setenv("SMILEID_ID_TYPES", json.dumps({"GH": ["PASSPORT"]}))       # no "*" entry
    r = _start(api, "BR")
    assert r.status_code == 200 and r.json()["provider"] == "didit" and not api.calls["smile"]


def test_bad_smile_id_id_type_config_never_breaks_the_start(api):
    api.monkeypatch.setenv("SMILEID_ID_TYPES", "{not json")
    assert _start(api, "GH").json()["provider"] == "didit"
