"""
Manual KYC with uploaded ID photos + selfie: reviewed by an admin, erased after the decision.

Real routes, real user/admin tokens, real image processing (Pillow); Supabase is the in-memory fake and the storage
bucket is an in-memory dict. Not covered here: the real Supabase Storage bucket and the SQL itself.
"""
import importlib
import io
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image


def _mod(name):
    return importlib.import_module(name)


def _jpeg(color=(200, 30, 30), size=(300, 200), exif=True):
    img = Image.new("RGB", size, color)
    out = io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretPhoneMaker"          # Make
        ex[0x8825] = {1: "N", 2: (5.0, 36.0, 0.0)}   # a GPS block
        img.save(out, format="JPEG", exif=ex)
    else:
        img.save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture
def api(fake_supabase, monkeypatch):
    for k, v in {"XERA_TOKEN_SECRET": "user-secret", "ADMIN_TOKEN_SECRET": "admin-secret", "XERA_KYC_DOC_UPLOAD": "true"}.items():
        monkeypatch.setenv(k, v)
    for k in ("XERA_KYC_ALLOW_MANUAL", "XERA_KYC_DIDIT_ENABLED", "XERA_KYC_SMILEID_ENABLED", "XERA_KYC_DOC_RETENTION_DAYS"):
        monkeypatch.delenv(k, raising=False)
    rr, ua, aa, kd = _mod("xera.routes_readiness"), _mod("xera.user_auth"), _mod("xera.admin_auth"), _mod("xera.kyc_documents")
    bucket, state = {}, {"remove_fails": False, "put_fail_after": None, "puts": 0}

    def put(path, data):
        state["puts"] += 1
        if state["put_fail_after"] is not None and state["puts"] > state["put_fail_after"]:
            raise RuntimeError("storage down")
        bucket[path] = data

    def remove(paths):
        if state["remove_fails"]:
            raise RuntimeError("storage down")
        for p in paths:
            bucket.pop(p, None)

    monkeypatch.setattr(kd, "_put", put)
    monkeypatch.setattr(kd, "_get", lambda path: bucket[path])
    monkeypatch.setattr(kd, "_remove", remove)

    app = FastAPI()
    app.include_router(rr.router, prefix="/api/xera")
    app.include_router(rr.admin_router, prefix="/api/admin/xera")
    fake_supabase.store["admin_agents"] = [{"user_id": 7, "is_active": True}, {"user_id": 8, "is_active": True}, {"user_id": 9, "is_active": False}]
    fake_supabase.store["users"] = [{"id": i} for i in (1, 2, 7, 8)]
    return types.SimpleNamespace(
        client=TestClient(app), fake=fake_supabase, bucket=bucket, state=state, monkeypatch=monkeypatch,
        h=lambda uid: {"Authorization": f"Bearer {ua.make_user_token(uid)}"},
        a=lambda uid: {"Authorization": f"Bearer {aa.make_admin_token(uid)}"},
    )


def _row(api, uid=1):
    return next((r for r in api.fake.store.get("xera_kyc", []) if r["user_id"] == uid), None)


def _docs(api, uid=1, live=True):
    rows = [d for d in api.fake.store.get("xera_kyc_documents", []) if d["user_id"] == uid]
    return [d for d in rows if not d.get("deleted_at")] if live else rows


def _upload(api, uid=1, *, id_type="national_id", consent="true", front=None, back="default", selfie=None, extra=None):
    files = {"id_front": ("front.jpg", front if front is not None else _jpeg(), "image/jpeg"),
             "selfie": ("me.jpg", selfie if selfie is not None else _jpeg((20, 90, 200)), "image/jpeg")}
    if back == "default":
        back = _jpeg((30, 200, 30)) if id_type != "passport" else None
    if back is not None:
        files["id_back"] = ("back.jpg", back, "image/jpeg")
    data = {"legal_name": "Ama Mensah", "country": "GH", "id_type": id_type, "consent": consent, **(extra or {})}
    return api.client.post("/api/xera/kyc/documents", headers=api.h(uid), data=data, files=files)


def _view_all(api, uid=1, admin=7):
    docs = api.client.get(f"/api/admin/xera/kyc/{uid}/documents", headers=api.a(admin)).json()["documents"]
    for d in docs:
        assert api.client.get(f"/api/admin/xera/kyc/documents/{d['id']}/image", headers=api.a(admin)).status_code == 200
    return docs


def _review(api, uid, decision, note="", admin=7):
    return api.client.post(f"/api/admin/xera/kyc/{uid}/review", headers=api.a(admin), json={"decision": decision, "note": note})


# ================================================================ submit
def test_upload_creates_a_pending_case_with_three_clean_private_files(api):
    r = _upload(api)
    assert r.status_code == 200 and r.json()["kyc"]["status"] == "PENDING"
    row = _row(api)
    assert (row["status"], row["method"], row["country"], row["id_type"]) == ("PENDING", "MANUAL", "GH", "national_id")
    assert row["docs_consent_at"] and row["docs_consent_version"] == "1" and row["reviewed_by"] is None
    docs = _docs(api)
    assert sorted(d["kind"] for d in docs) == ["id_back", "id_front", "selfie"]
    assert all(d["storage_path"].startswith("kyc/1/") and d["storage_path"].endswith(".jpg") for d in docs)
    for path, data in api.bucket.items():
        img = Image.open(io.BytesIO(data))
        assert img.format == "JPEG" and not dict(img.getexif()) and b"SecretPhoneMaker" not in data      # EXIF/GPS gone
    state = api.client.get("/api/xera/readiness", headers=api.h(1)).json()
    assert "kyc" in state and "storage_path" not in str(state) and "kyc/1/" not in str(state)           # never exposed to the user


def test_passport_needs_no_back_but_other_ids_do(api):
    assert _upload(api, id_type="passport").status_code == 200 and len(_docs(api)) == 2
    api.fake.store.clear()
    api.bucket.clear()
    api.fake.store["users"] = [{"id": 1}]
    assert _upload(api, id_type="drivers_license", back=None).status_code == 400
    assert _docs(api) == [] and _row(api) is None


def test_consent_is_required_and_nothing_is_stored_without_it(api):
    assert _upload(api, consent="").status_code == 400
    assert _upload(api, consent="false").status_code == 400
    assert api.bucket == {} and _row(api) is None


def test_bad_files_are_refused_and_nothing_is_stored(api):
    assert _upload(api, front=b"<html>not an image</html>").status_code == 400
    assert _upload(api, selfie=b"GIF89a....").status_code == 400
    assert _upload(api, front=b"\xff" * (9 * 1024 * 1024)).status_code in (400, 413)
    bomb = io.BytesIO()
    Image.new("L", (12000, 12000)).save(bomb, format="PNG")           # tiny file, 144 million pixels
    assert _upload(api, front=bomb.getvalue()).status_code == 400
    assert api.bucket == {} and _row(api) is None and _docs(api, live=False) == []


def test_a_png_is_accepted_and_stored_as_jpeg(api):
    buf = io.BytesIO()
    Image.new("RGBA", (200, 100), (10, 200, 10, 128)).save(buf, format="PNG")
    assert _upload(api, front=buf.getvalue()).status_code == 200
    assert all(Image.open(io.BytesIO(v)).format == "JPEG" for v in api.bucket.values())


def test_the_browser_cannot_set_a_status_or_name_another_user(api):
    r = _upload(api, extra={"status": "VERIFIED", "user_id": "2", "reviewed_by": "7"})
    assert r.status_code == 200
    assert (_row(api)["status"], _row(api)["reviewed_by"]) == ("PENDING", None) and _row(api, 2) is None
    assert api.client.post("/api/xera/kyc/documents", data={"legal_name": "x y z", "country": "GH", "id_type": "passport", "consent": "true"}).status_code in (401, 422)


def test_no_session_means_no_upload(api):
    files = {"id_front": ("a.jpg", _jpeg(), "image/jpeg"), "selfie": ("b.jpg", _jpeg(), "image/jpeg")}
    r = api.client.post("/api/xera/kyc/documents", data={"legal_name": "Ama Mensah", "country": "GH", "id_type": "passport", "consent": "true"}, files=files)
    assert r.status_code == 401 and api.bucket == {}


def test_cannot_submit_while_pending_or_verified(api):
    _upload(api)
    assert _upload(api).status_code == 409
    _row(api)["status"] = "VERIFIED"
    assert _upload(api).status_code == 409


def test_a_storage_failure_halfway_submits_nothing_and_leaves_no_files(api):
    api.state["put_fail_after"] = 1
    r = _upload(api)
    assert r.status_code == 503
    assert api.bucket == {} and _docs(api) == [] and _row(api) is None


def test_upload_off_means_503_and_text_form_stays_as_before(api):
    api.monkeypatch.setenv("XERA_KYC_DOC_UPLOAD", "false")
    assert _upload(api).status_code == 503
    r = api.client.post("/api/xera/kyc/submit", headers=api.h(1), json={"legal_name": "Ama Mensah", "country": "GH", "id_type": "passport", "id_number": "G1234567"})
    assert r.status_code == 200


def test_text_only_submit_is_closed_while_uploads_are_on(api):
    r = api.client.post("/api/xera/kyc/submit", headers=api.h(1), json={"legal_name": "Ama Mensah", "country": "GH", "id_type": "passport", "id_number": "G1234567"})
    assert r.status_code == 409 and _row(api) is None
    assert api.client.get("/api/xera/readiness", headers=api.h(1)).json()["kyc_options"]["upload_enabled"] is True


def test_resubmitting_after_a_request_for_more_info_replaces_and_erases_the_old_files(api):
    _upload(api)
    old = set(api.bucket)
    _view_all(api)
    assert _review(api, 1, "INFO_REQUIRED", "Back of the ID is blurry").status_code == 200
    assert _upload(api).status_code == 200
    assert not (old & set(api.bucket)) and len(api.bucket) == 3
    assert all(d["deleted_reason"] == "RESUBMITTED" for d in _docs(api, live=False) if d["storage_path"] in old)


# ================================================================ admin viewing
def test_only_an_active_admin_can_list_or_view_and_never_their_own(api):
    _upload(api)
    doc = _docs(api)[0]["id"]
    assert api.client.get("/api/admin/xera/kyc/1/documents", headers=api.h(1)).status_code == 401        # a user token
    assert api.client.get("/api/admin/xera/kyc/1/documents").status_code == 401
    assert api.client.get("/api/admin/xera/kyc/1/documents", headers=api.a(9)).status_code == 403        # revoked admin
    assert api.client.get(f"/api/admin/xera/kyc/documents/{doc}/image", headers=api.h(1)).status_code == 401
    assert api.client.get(f"/api/admin/xera/kyc/documents/{doc}/image", headers=api.a(9)).status_code == 403
    assert api.fake.store.get("xera_kyc_access_log", []) == []
    _upload(api, uid=7)                                                   # an admin who also submitted their own KYC
    own = _docs(api, 7)[0]["id"]
    assert api.client.get(f"/api/admin/xera/kyc/documents/{own}/image", headers=api.a(7)).status_code == 403
    assert api.client.get("/api/admin/xera/kyc/7/documents", headers=api.a(7)).status_code == 403


def test_the_list_has_metadata_only_and_the_queue_shows_the_count(api):
    _upload(api)
    docs = api.client.get("/api/admin/xera/kyc/1/documents", headers=api.a(7)).json()["documents"]
    assert len(docs) == 3 and all(set(d) == {"id", "kind", "size_bytes", "created_at"} for d in docs)
    item = api.client.get("/api/admin/xera/kyc?status=PENDING", headers=api.a(7)).json()["items"][0]
    assert item["documents"] == 3 and "storage_path" not in item and "sha256" not in item


def test_every_view_is_logged_with_the_admin_id_and_comes_back_uncacheable(api):
    _upload(api)
    doc = _docs(api)[0]
    r = api.client.get(f"/api/admin/xera/kyc/documents/{doc['id']}/image", headers=api.a(8))
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content == api.bucket[doc["storage_path"]]
    assert "no-store" in r.headers["cache-control"] and r.headers["x-content-type-options"] == "nosniff"
    log = api.fake.store["xera_kyc_access_log"]
    assert [(l["admin_id"], l["user_id"], l["document_id"], l["action"]) for l in log] == [(8, 1, doc["id"], "view")]


def test_if_the_access_log_cannot_be_written_no_image_is_shown(api):
    _upload(api)
    doc = _docs(api)[0]["id"]

    class Boom:
        def insert(self, *_a, **_k):
            raise RuntimeError("db down")
    real = api.fake.table
    api.fake.table = lambda name: Boom() if name == "xera_kyc_access_log" else real(name)
    r = api.client.get(f"/api/admin/xera/kyc/documents/{doc}/image", headers=api.a(7))
    assert r.status_code == 503 and r.content[:2] != b"\xff\xd8"


# ================================================================ the decision, and the erase
def test_verify_is_refused_until_this_admin_has_opened_every_image(api):
    _upload(api)
    assert _review(api, 1, "VERIFIED").status_code == 409
    docs = api.client.get("/api/admin/xera/kyc/1/documents", headers=api.a(7)).json()["documents"]
    api.client.get(f"/api/admin/xera/kyc/documents/{docs[0]['id']}/image", headers=api.a(7))
    assert _review(api, 1, "VERIFIED").status_code == 409                      # still two unseen
    _view_all(api, admin=8)                                                    # another admin looking does not count for 7
    assert _review(api, 1, "VERIFIED", admin=7).status_code == 409
    assert _row(api)["status"] == "PENDING" and len(api.bucket) == 3


def test_verify_records_the_admin_and_erases_every_image(api):
    _upload(api)
    _view_all(api)
    r = _review(api, 1, "VERIFIED")
    assert r.status_code == 200 and r.json()["kyc"]["documents_erased"] == 3 and r.json()["kyc"]["documents_erase_failed"] == 0
    row = _row(api)
    assert (row["status"], row["reviewed_by"]) == ("VERIFIED", 7) and row["reviewed_at"]
    assert api.bucket == {}                                                    # gone from storage
    rows = _docs(api, live=False)
    assert len(rows) == 3 and all(d["deleted_at"] and d["deleted_reason"] == "VERIFIED" for d in rows)
    assert len(api.fake.store["xera_kyc_access_log"]) == 3                     # the who-looked record stays
    assert api.client.get("/api/xera/readiness", headers=api.h(1)).json()["kyc"]["status"] == "VERIFIED"
    assert api.client.get(f"/api/admin/xera/kyc/documents/{rows[0]['id']}/image", headers=api.a(7)).status_code == 404


def test_failing_a_case_erases_the_images_too(api):
    _upload(api)
    assert _review(api, 1, "FAILED", "ID does not match the selfie").status_code == 200
    assert api.bucket == {} and all(d["deleted_reason"] == "FAILED" for d in _docs(api, live=False))
    assert _upload(api).status_code == 200                                      # the user can try again


def test_if_an_erase_fails_the_decision_stands_and_a_retry_cleans_up(api):
    _upload(api)
    _view_all(api)
    api.state["remove_fails"] = True
    r = _review(api, 1, "VERIFIED")
    assert r.status_code == 200 and r.json()["kyc"]["documents_erase_failed"] == 3 and _row(api)["status"] == "VERIFIED"
    assert len(api.bucket) == 3 and len(_docs(api)) == 3                        # still there, still tracked
    api.state["remove_fails"] = False
    p = api.client.post("/api/admin/xera/kyc/documents/purge-expired", headers=api.a(7))
    assert p.status_code == 200 and p.json()["erased"] == 3 and api.bucket == {} and _docs(api) == []


def test_unreviewed_documents_expire_and_the_user_is_asked_to_upload_again(api):
    _upload(api)
    for d in api.fake.store["xera_kyc_documents"]:
        d["created_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    _upload(api, uid=2)                                                         # a fresh case must be untouched
    p = api.client.post("/api/admin/xera/kyc/documents/purge-expired", headers=api.a(7))
    assert p.status_code == 200
    assert _docs(api) == [] and len(_docs(api, 2)) == 3
    assert _row(api)["status"] == "INFO_REQUIRED" and "upload them again" in _row(api)["review_note"]
    assert _row(api, 2)["status"] == "PENDING"
    assert api.client.post("/api/admin/xera/kyc/documents/purge-expired", headers=api.h(1)).status_code == 401


def test_the_retention_period_is_configurable(api):
    api.monkeypatch.setenv("XERA_KYC_DOC_RETENTION_DAYS", "3")
    _upload(api)
    for d in api.fake.store["xera_kyc_documents"]:
        d["created_at"] = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    assert api.client.post("/api/admin/xera/kyc/documents/purge-expired", headers=api.a(7)).json()["erased"] == 3


def test_a_verified_user_is_still_gated_by_the_fee_and_everything_else(api):
    _upload(api)
    _view_all(api)
    _review(api, 1, "VERIFIED")
    missing = api.client.get("/api/xera/readiness", headers=api.h(1)).json()["missing"]
    assert "kyc_not_verified" not in missing and "fee_not_paid" in missing


def test_overdue_images_are_erased_just_by_an_admin_opening_the_queue(api):
    _upload(api)
    for d in api.fake.store["xera_kyc_documents"]:
        d["created_at"] = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    api.client.get("/api/admin/xera/kyc?status=PENDING", headers=api.a(7))
    assert api.bucket == {} and _docs(api) == [] and _row(api)["status"] == "INFO_REQUIRED"
