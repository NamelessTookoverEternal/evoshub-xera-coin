"""
Product switches: real routes, real admin tokens, real guard dependency. Supabase is an in-memory fake.
Not covered: the SQL itself and the browser script.
"""
import importlib
import re
import sys
import types
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


class Q:
    def __init__(self, store, name):
        self.store, self.name, self.f, self.op, self.payload, self.conflict = store, name, [], "select", None, None

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.f.append(lambda r: r.get(k) == v); return self
    def order(self, *_a, **_k): return self
    def limit(self, _n): return self
    def insert(self, row): self.op, self.payload = "insert", dict(row); return self
    def upsert(self, row, on_conflict=None): self.op, self.payload, self.conflict = "upsert", dict(row), on_conflict; return self

    def execute(self):
        table = self.store.setdefault(self.name, [])
        if self.op == "insert":
            table.append(self.payload)
            return types.SimpleNamespace(data=[self.payload])
        if self.op == "upsert":
            for r in table:
                if r.get(self.conflict) == self.payload.get(self.conflict):
                    r.update(self.payload)
                    return types.SimpleNamespace(data=[r])
            table.append(self.payload)
            return types.SimpleNamespace(data=[self.payload])
        return types.SimpleNamespace(data=[r for r in table if all(f(r) for f in self.f)])


class FakeDB:
    def __init__(self): self.store, self.broken = {}, False
    def table(self, name):
        if self.broken:
            raise RuntimeError("db down")
        return Q(self.store, name)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN_SECRET", "admin-secret")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    db = FakeDB()
    sys.modules["main"].supabase = db
    for m in ("routes.product_switches", "xera.admin_auth", "utils.product_switches"):
        sys.modules.pop(m, None)
    ps = importlib.import_module("utils.product_switches")
    rp = importlib.import_module("routes.product_switches")
    aa = importlib.import_module("xera.admin_auth")
    monkeypatch.setattr(ps, "_client", lambda: db)
    ps.clear_cache()
    app = FastAPI()
    app.include_router(rp.router, prefix="/api/products")
    app.include_router(rp.admin_router, prefix="/api/admin/products")

    @app.post("/new-order", dependencies=[Depends(ps.require_on("evosdata"))])
    def new_order(): return {"ok": True}

    @app.post("/webhook")        # webhooks are never guarded
    def webhook(): return {"ok": True}

    @app.post("/xera-thing", dependencies=[Depends(ps.require_on("xera"))])
    def xera_thing(): return {"ok": True}

    db.store["admin_agents"] = [{"user_id": 7, "is_active": True}, {"user_id": 9, "is_active": False}]
    return types.SimpleNamespace(c=TestClient(app), db=db, ps=ps,
                                 a=lambda uid=7: {"Authorization": f"Bearer {aa.make_admin_token(uid)}"})


def _off(api, key, **extra):
    return api.c.patch(f"/api/admin/products/{key}", headers=api.a(), json={"enabled": False, **extra})


def test_everything_is_on_when_table_is_empty(api):
    r = api.c.get("/api/products/status")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=30"
    prods = r.json()["products"]
    assert set(prods) == {"evosdata", "evosgpt", "xera", "games", "roadmap", "website"}
    assert all(p["enabled"] for p in prods.values())


def test_public_status_never_exposes_enforce_or_admin_ids(api):
    _off(api, "games")
    p = api.c.get("/api/products/status").json()["products"]["games"]
    assert set(p) == {"enabled", "message"} and p["enabled"] is False


def test_only_active_admins_can_list_or_change(api):
    assert api.c.get("/api/admin/products").status_code == 401
    assert api.c.patch("/api/admin/products/games", json={"enabled": False}).status_code == 401
    assert api.c.patch("/api/admin/products/games", headers={"Authorization": "Bearer nope.nope"}, json={"enabled": False}).status_code == 401
    assert api.c.patch("/api/admin/products/games", headers=api.a(9), json={"enabled": False}).status_code == 403   # revoked
    assert api.c.patch("/api/admin/products/games", headers=api.a(123), json={"enabled": False}).status_code == 403  # never an agent
    assert api.db.store.get("product_switches", []) == []


def test_admin_can_switch_off_and_on_and_it_is_audited(api):
    r = _off(api, "games", message="  Games are   resting.  ")
    assert r.status_code == 200
    assert r.json()["product"]["enabled"] is False and r.json()["product"]["message"] == "Games are resting."
    assert api.c.get("/api/products/status").json()["products"]["games"] == {"enabled": False, "message": "Games are resting."}
    assert api.c.patch("/api/admin/products/games", headers=api.a(), json={"enabled": True}).status_code == 200
    assert api.c.get("/api/products/status").json()["products"]["games"]["enabled"] is True
    log = api.db.store["xera_admin_actions"]
    assert [x["action"] for x in log] == ["PRODUCT_SWITCH_CHANGED"] * 2
    assert log[0]["admin_id"] == 7 and log[0]["old_value"]["enabled"] is True and log[0]["new_value"]["enabled"] is False
    assert api.db.store["product_switches"][0]["updated_by"] == 7


def test_unknown_product_empty_patch_and_long_message_are_rejected(api):
    assert api.c.patch("/api/admin/products/nope", headers=api.a(), json={"enabled": False}).status_code == 404
    assert api.c.patch("/api/admin/products/games", headers=api.a(), json={}).status_code == 400
    assert api.c.patch("/api/admin/products/games", headers=api.a(), json={"message": "x" * 201}).status_code == 422


def test_xera_needs_confirmation_to_switch_off(api):
    r = _off(api, "xera")
    assert r.status_code == 409
    assert api.c.get("/api/products/status").json()["products"]["xera"]["enabled"] is True
    assert _off(api, "xera", confirm=True).status_code == 200
    assert api.c.get("/api/products/status").json()["products"]["xera"]["enabled"] is False
    # switching ON never needs confirmation
    assert api.c.patch("/api/admin/products/xera", headers=api.a(), json={"enabled": True}).status_code == 200


def test_new_orders_are_refused_only_when_off_and_enforced(api):
    assert api.c.post("/new-order").status_code == 200
    _off(api, "evosdata", message="Back at 6pm.")
    r = api.c.post("/new-order")
    assert r.status_code == 503 and r.json()["detail"] == "Back at 6pm." and r.headers["retry-after"] == "300"
    assert api.c.post("/webhook").status_code == 200                       # paid orders / provider callbacks still finish
    api.c.patch("/api/admin/products/evosdata", headers=api.a(), json={"enforce": False})
    assert api.c.post("/new-order").status_code == 200                     # grey only
    api.c.patch("/api/admin/products/evosdata", headers=api.a(), json={"enforce": True, "enabled": True})
    assert api.c.post("/new-order").status_code == 200                     # back on


def test_default_message_names_the_product(api):
    _off(api, "evosdata")
    assert api.c.post("/new-order").json()["detail"] == "EVOS Data is switched off for now. Please check back soon."


def test_xera_is_grey_only_by_default_so_claims_and_mining_are_not_blocked(api):
    _off(api, "xera", confirm=True)
    assert api.c.post("/xera-thing").status_code == 200


def test_fails_open_when_the_database_is_down(api):
    _off(api, "evosdata")
    assert api.c.post("/new-order").status_code == 503
    api.ps.clear_cache()
    api.db.broken = True
    assert api.c.post("/new-order").status_code == 200
    prods = api.c.get("/api/products/status").json()["products"]
    assert all(p["enabled"] for p in prods.values())


def test_last_good_answer_is_kept_briefly_if_the_database_blips(api):
    _off(api, "evosdata")
    assert api.c.post("/new-order").status_code == 503
    api.ps._cache["at"] = 0            # cache expired
    api.db.broken = True
    assert api.c.post("/new-order").status_code == 503   # still off: a blip must not re-open the product


def test_new_order_and_chat_routes_are_guarded_and_webhooks_are_not():
    root = Path(__file__).resolve().parents[1] / "services"
    data = (root / "evosdata" / "core.py").read_text()
    gpt = (root / "evosgpt" / "core.py").read_text()
    for path in ["/orders/create", "/checkers/create", "/afa/create", "/agent/buy-data", "/agent/buy-checker",
                 "/agent/buy-afa", "/store/order", "/store/order/checker"]:
        assert f'@router.post("{path}", dependencies=[Depends(_evosdata_on)])' in data, path
    for path in ["/chat", "/image/generate", "/image/edit", "/document/generate"]:
        assert f'@router.post("{path}", dependencies=[Depends(_evosgpt_on)])' in gpt, path
    for src in (data, gpt):
        for m in re.finditer(r'@router\.\w+\("([^"]*(webhook|sync|track|verify|status)[^"]*)"[^\n]*\)', src):
            assert "dependencies=" not in m.group(0), m.group(1)
