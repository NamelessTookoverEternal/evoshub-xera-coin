"""
App Updates channel (phase 1): real routes, real admin tokens, real image processing (Pillow).
Supabase table access and the storage bucket are in-memory fakes. Not covered: the real bucket and the SQL itself.
"""
import importlib
import io
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image


def _jpeg(size=(300, 200), color=(200, 30, 30), exif=True):
    img = Image.new("RGB", size, color)
    out = io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretPhoneMaker"
        ex[0x8825] = {1: "N", 2: (5.0, 36.0, 0.0)}
        img.save(out, format="JPEG", exif=ex)
    else:
        img.save(out, format="JPEG")
    return out.getvalue()


def _png(alpha=False):
    out = io.BytesIO()
    Image.new("RGBA" if alpha else "RGB", (80, 60), (10, 200, 10, 128) if alpha else (10, 200, 10)).save(out, format="PNG")
    return out.getvalue()


class Q:
    def __init__(self, rows, name, store):
        self.rows, self.name, self.store = rows, name, store
        self.f, self._lim, self._desc, self._op, self._patch, self._ins = [], None, False, "select", None, None

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.f.append(lambda r: r.get(k) == v); return self
    def lt(self, k, v): self.f.append(lambda r: r.get(k) < v); return self
    def order(self, _k, desc=False): self._desc = desc; return self
    def limit(self, n): self._lim = n; return self
    def insert(self, row): self._op, self._ins = "insert", dict(row); return self
    def update(self, patch): self._op, self._patch = "update", patch; return self
    def delete(self): self._op = "delete"; return self

    def execute(self):
        table = self.store.setdefault(self.name, [])
        if self._op == "insert":
            self._ins["id"] = max([r["id"] for r in table] + [0]) + 1
            self._ins.setdefault("created_at", f"2026-11-05T10:00:{self._ins['id']:02d}+00:00")
            self._ins.setdefault("edited_at", None)
            table.append(self._ins)
            return types.SimpleNamespace(data=[self._ins])
        hit = [r for r in table if all(f(r) for f in self.f)]
        if self._op == "update":
            for r in hit:
                r.update(self._patch)
            return types.SimpleNamespace(data=hit)
        if self._op == "delete":
            for r in hit:
                table.remove(r)
            return types.SimpleNamespace(data=hit)
        hit = sorted(hit, key=lambda r: r.get("id", 0), reverse=self._desc)
        return types.SimpleNamespace(data=hit[: self._lim] if self._lim else hit)


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, name): return Q(self.store.setdefault(name, []), name, self.store)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN_SECRET", "admin-secret")
    monkeypatch.setenv("XERA_TOKEN_SECRET", "user-secret")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    import sys
    db = FakeDB()
    sys.modules["main"].supabase = db
    for m in ("routes.updates", "xera.admin_auth", "xera.user_auth"):
        sys.modules.pop(m, None)
    up = importlib.import_module("routes.updates")
    aa = importlib.import_module("xera.admin_auth")
    ua = importlib.import_module("xera.user_auth")
    bucket, state = {}, {"put_fail_after": None, "puts": 0, "remove_fails": False}

    def put(path, data, ctype):
        state["puts"] += 1
        if state["put_fail_after"] is not None and state["puts"] > state["put_fail_after"]:
            raise RuntimeError("storage down")
        bucket[path] = (data, ctype)

    def remove(paths):
        if state["remove_fails"]:
            raise RuntimeError("storage down")
        for p in paths:
            bucket.pop(p, None)

    monkeypatch.setattr(up, "_put", put)
    monkeypatch.setattr(up, "_remove", remove)
    app = FastAPI()
    app.include_router(up.router, prefix="/api/updates")
    app.include_router(up.admin_router, prefix="/api/admin/updates")
    db.store["admin_agents"] = [{"user_id": 7, "is_active": True}, {"user_id": 9, "is_active": False}]
    return types.SimpleNamespace(
        c=TestClient(app), db=db, bucket=bucket, state=state, up=up,
        a=lambda uid: {"Authorization": f"Bearer {aa.make_admin_token(uid)}"},
        u=lambda uid: {"Authorization": f"Bearer {ua.make_user_token(uid)}"},
    )


def _post(api, body="Hello Ghana", files=(), uid=7):
    fl = [("images", (f"p{i}.jpg", data, "image/jpeg")) for i, data in enumerate(files)]
    return api.c.post("/api/admin/updates", headers=api.a(uid), data={"body": body}, files=fl or None)


# ------------------------------------------------------------ who may post
def test_active_admin_can_post_text(api):
    r = _post(api)
    assert r.status_code == 200
    u = r.json()["update"]
    assert u["body"] == "Hello Ghana" and u["badge"] == "Evoxera Admin" and u["images"] == []
    assert api.db.store["app_updates"][0]["author_id"] == 7


def test_no_token_bad_token_and_revoked_admin_cannot_post(api):
    assert api.c.post("/api/admin/updates", data={"body": "x"}).status_code == 401
    assert api.c.post("/api/admin/updates", headers={"Authorization": "Bearer nope.nope"}, data={"body": "x"}).status_code == 401
    assert _post(api, uid=9).status_code == 403          # token valid, agent deactivated
    assert _post(api, uid=123).status_code == 403        # valid token, never an agent
    assert api.db.store.get("app_updates", []) == []


def test_normal_user_xera_style_token_cannot_post(api):
    # A token signed with a different secret (e.g. an ordinary user token) must not verify.
    import base64, hashlib, hmac, json, time
    payload = base64.urlsafe_b64encode(json.dumps({"uid": 7, "exp": int(time.time()) + 600}).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(hmac.new(b"user-secret", payload.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    r = api.c.post("/api/admin/updates", headers={"Authorization": f"Bearer {payload}.{sig}"}, data={"body": "x"})
    assert r.status_code == 401


def test_edit_and_delete_require_admin(api):
    pid = _post(api).json()["update"]["id"]
    assert api.c.patch(f"/api/admin/updates/{pid}", json={"body": "hack"}).status_code == 401
    assert api.c.delete(f"/api/admin/updates/{pid}").status_code == 401
    assert api.c.delete(f"/api/admin/updates/{pid}", headers=api.a(9)).status_code == 403
    assert api.db.store["app_updates"][0]["body"] == "Hello Ghana"


# ------------------------------------------------------------ content rules
def test_empty_post_refused_and_text_limit(api):
    assert _post(api, body="   ").status_code == 400
    assert _post(api, body="x" * 4001).status_code == 400
    assert _post(api, body="x" * 4000).status_code == 200


def test_text_is_stored_as_typed_not_html_escaped_and_control_chars_dropped(api):
    r = _post(api, body="Tom & Jerry <b>2 < 3</b>\r\n\x00\x07line2\n\n\n\n\nend")
    assert r.json()["update"]["body"] == "Tom & Jerry <b>2 < 3</b>\nline2\n\nend"


def test_more_than_four_images_refused_and_nothing_stored(api):
    r = _post(api, files=[_jpeg()] * 5)
    assert r.status_code == 400 and api.bucket == {} and api.db.store.get("app_updates", []) == []


# ------------------------------------------------------------ images
def test_image_is_reencoded_strips_exif_and_gets_random_name(api):
    original = _jpeg(exif=True)
    assert b"SecretPhoneMaker" in original
    r = _post(api, files=[original], body="")
    assert r.status_code == 200
    (path, (data, ctype)), = api.bucket.items()
    assert ctype == "image/jpeg" and path.endswith(".jpg") and "p0" not in path
    assert b"SecretPhoneMaker" not in data
    assert not Image.open(io.BytesIO(data)).getexif()
    img = r.json()["update"]["images"][0]
    assert img["url"] == f"https://proj.supabase.co/storage/v1/object/public/app-updates/{path}"
    assert img["download_url"].endswith(f"?download=evoxera-update-1-1.jpg")


def test_png_with_transparency_stays_png(api):
    r = api.c.post("/api/admin/updates", headers=api.a(7), data={"body": "logo"},
                   files=[("images", ("l.png", _png(alpha=True), "image/png"))])
    assert r.status_code == 200
    (path, (data, ctype)), = api.bucket.items()
    assert ctype == "image/png" and path.endswith(".png")


def test_huge_photo_is_shrunk(api):
    r = _post(api, files=[_jpeg(size=(4000, 3000))], body="big")
    assert r.status_code == 200
    img = r.json()["update"]["images"][0]
    assert max(img["width"], img["height"]) <= 1600


@pytest.mark.parametrize("name,payload", [
    ("x.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
    ("x.jpg", b"not an image at all"),
    ("x.jpg", b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"),
    ("x.jpg", b""),
])
def test_non_images_are_refused_even_with_image_names(api, name, payload):
    r = api.c.post("/api/admin/updates", headers=api.a(7), data={"body": "t"}, files=[("images", (name, payload, "image/jpeg"))])
    assert r.status_code == 400 and api.bucket == {} and api.db.store.get("app_updates", []) == []


def test_one_bad_image_among_good_ones_stores_nothing(api):
    r = _post(api, files=[_jpeg(), b"junk", _jpeg()])
    assert r.status_code == 400 and api.bucket == {} and api.db.store.get("app_updates", []) == []


def test_upload_failure_midway_cleans_up_and_saves_no_post(api):
    api.state["put_fail_after"] = 1
    r = _post(api, files=[_jpeg(), _jpeg()])
    assert r.status_code == 502 and api.bucket == {} and api.db.store.get("app_updates", []) == []


def test_insert_failure_removes_uploaded_images(api, monkeypatch):
    def boom(*_a, **_k): raise RuntimeError("db down")
    real_table = api.db.table
    monkeypatch.setattr(api.db, "table", lambda n: (_ for _ in ()).throw(RuntimeError("db down")) if n == "app_updates" else real_table(n))
    r = _post(api, files=[_jpeg()])
    assert r.status_code == 502 and api.bucket == {}


# ------------------------------------------------------------ public read
def test_public_read_needs_no_login_newest_first_and_pages(api):
    for i in range(5):
        _post(api, body=f"post {i}")
    r = api.c.get("/api/updates?limit=2")
    j = r.json()
    assert r.status_code == 200 and [u["body"] for u in j["updates"]] == ["post 4", "post 3"] and j["has_more"] is True
    j2 = api.c.get(f"/api/updates?limit=2&before={j['updates'][-1]['id']}").json()
    assert [u["body"] for u in j2["updates"]] == ["post 2", "post 1"] and j2["has_more"] is True
    j3 = api.c.get("/api/updates?limit=2&before=2").json()
    assert [u["body"] for u in j3["updates"]] == ["post 0"] and j3["has_more"] is False


def test_public_read_never_exposes_author_or_storage_paths(api):
    _post(api, files=[_jpeg()])
    u = api.c.get("/api/updates").json()["updates"][0]
    assert set(u) == {"id", "body", "badge", "created_at", "edited_at", "images"}
    assert set(u["images"][0]) == {"url", "download_url", "width", "height"}


def test_limit_is_clamped(api):
    for i in range(35):
        _post(api, body=f"p{i}")
    assert len(api.c.get("/api/updates?limit=9999").json()["updates"]) == 30
    assert len(api.c.get("/api/updates?limit=-5").json()["updates"]) == 1


# ------------------------------------------------------------ edit / delete
def test_edit_changes_text_and_marks_edited(api):
    pid = _post(api).json()["update"]["id"]
    r = api.c.patch(f"/api/admin/updates/{pid}", headers=api.a(7), json={"body": "Corrected"})
    assert r.status_code == 200 and r.json()["update"]["body"] == "Corrected" and r.json()["update"]["edited_at"]
    assert api.c.patch("/api/admin/updates/999", headers=api.a(7), json={"body": "x"}).status_code == 404


def test_edit_cannot_blank_a_text_only_post_but_can_on_an_image_post(api):
    t = _post(api).json()["update"]["id"]
    assert api.c.patch(f"/api/admin/updates/{t}", headers=api.a(7), json={"body": " "}).status_code == 400
    i = _post(api, files=[_jpeg()], body="cap").json()["update"]["id"]
    assert api.c.patch(f"/api/admin/updates/{i}", headers=api.a(7), json={"body": ""}).status_code == 200


def test_delete_removes_post_and_its_images(api):
    pid = _post(api, files=[_jpeg(), _jpeg()]).json()["update"]["id"]
    assert len(api.bucket) == 2
    r = api.c.delete(f"/api/admin/updates/{pid}", headers=api.a(7))
    assert r.status_code == 200 and api.bucket == {} and api.db.store["app_updates"] == []
    assert api.c.delete(f"/api/admin/updates/{pid}", headers=api.a(7)).status_code == 404


def test_delete_keeps_the_post_if_storage_fails_so_it_can_be_retried(api):
    pid = _post(api, files=[_jpeg()]).json()["update"]["id"]
    api.state["remove_fails"] = True
    assert api.c.delete(f"/api/admin/updates/{pid}", headers=api.a(7)).status_code == 502
    assert len(api.db.store["app_updates"]) == 1
    api.state["remove_fails"] = False
    assert api.c.delete(f"/api/admin/updates/{pid}", headers=api.a(7)).status_code == 200


# ------------------------------------------------------------ app shortcut check
def test_agent_status_true_only_for_active_agent_with_a_real_user_session(api):
    assert api.c.get("/api/updates/agent-status", headers=api.u(7)).json() == {"status": "ok", "is_agent": True}
    assert api.c.get("/api/updates/agent-status", headers=api.u(9)).json()["is_agent"] is False    # deactivated
    assert api.c.get("/api/updates/agent-status", headers=api.u(123)).json()["is_agent"] is False  # ordinary user
    assert api.c.get("/api/updates/agent-status").json()["is_agent"] is False                      # signed out
    assert api.c.get("/api/updates/agent-status", headers={"Authorization": "Bearer x.y"}).json()["is_agent"] is False


def test_an_admin_token_is_not_accepted_as_a_user_session_for_the_shortcut(api):
    # different secret: the admin token must not verify as an app user token
    assert api.c.get("/api/updates/agent-status", headers=api.a(7)).json()["is_agent"] is False
