import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.evosdata import core

class FakeTable:
    def __init__(s, rows): s.rows = rows
    def select(s, *_): return s
    def execute(s):
        class R: pass
        r = R(); r.data = s.rows; return r
class FakeSB:
    def __init__(s): s.rows=[{"network":"MTN","bundle":"1GB","price":5.0}]; s.calls=0
    def table(s, n): s.calls+=1; return FakeTable(s.rows)

def client(monkeypatch, sb):
    monkeypatch.setattr(core, "supabase", sb)
    monkeypatch.setattr(core.datamart_stock, "annotate", lambda rows: [r.update(in_stock=True) for r in rows] and rows)
    core._prices_cache.update(data=None, updated_at=None, loaded_mono=0.0)
    app = FastAPI(); app.state.limiter = core.limiter; app.include_router(core.router)
    return TestClient(app)

def test_served_from_cache_and_version(monkeypatch):
    sb = FakeSB(); c = client(monkeypatch, sb)
    r1 = c.get("/prices").json(); r2 = c.get("/prices").json()
    assert sb.calls == 1                      # second hit never touched Supabase
    assert r1["data"][0]["in_stock"] is True and r1["version"] == r2["version"]
    assert "in_stock" not in core._prices_cache["data"][0]   # cache not polluted
    sb.rows = [{"network":"MTN","bundle":"1GB","price":5.0},{"network":"MTN","bundle":"2GB","price":9.0}]
    core.refresh_prices_cache()
    r3 = c.get("/prices").json()
    assert len(r3["data"]) == 2 and r3["version"] != r1["version"]   # new GB size picked up

def test_failed_refresh_keeps_old_and_stale_self_heals(monkeypatch):
    sb = FakeSB(); c = client(monkeypatch, sb); c.get("/prices")
    class Boom:
        def table(s, n): raise RuntimeError("db down")
    monkeypatch.setattr(core, "supabase", Boom())
    assert core.refresh_prices_cache() is False
    assert len(c.get("/prices").json()["data"]) == 1                 # old copy kept
    monkeypatch.setattr(core, "supabase", sb)
    core._prices_cache["loaded_mono"] = time.monotonic() - core.PRICES_REFRESH_SECONDS * 3
    sb.rows = [{"network":"MTN","bundle":"1GB","price":6.0}]
    assert c.get("/prices").json()["data"][0]["price"] == 6.0        # reloaded itself
