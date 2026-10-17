"""
DataMart wallet -> automatic out-of-stock. No network, no real Supabase.
Run:  pytest tests/evosdata/test_datamart_stock.py
"""
import os
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.getcwd())
os.environ["DATAMART_API_KEY"] = "test-key"

from services.evosdata import datamart_stock as ds  # noqa: E402


class FakeQ:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op, self.payload, self.lim = db, table, [], "select", None, None

    def select(self, *a, **k): return self
    def eq(self, c, v): self.filters.append(lambda r: r.get(c) == v); return self
    def order(self, *a, **k): return self
    def limit(self, n): self.lim = n; return self
    def insert(self, p): self.op, self.payload = "insert", p; return self
    def upsert(self, p): self.op, self.payload = "upsert", p; return self

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        if self.op == "insert":
            rows.append(dict(self.payload))
            return types.SimpleNamespace(data=[dict(self.payload)])
        if self.op == "upsert":
            for r in rows:
                if r.get("id") == self.payload.get("id"):
                    r.update(self.payload)
                    break
            else:
                rows.append(dict(self.payload))
            return types.SimpleNamespace(data=[dict(self.payload)])
        out = [dict(r) for r in rows if all(f(r) for f in self.filters)]
        return types.SimpleNamespace(data=out[: self.lim] if self.lim else out)


class FakeDB:
    def __init__(self): self.t = {}
    def table(self, name): return FakeQ(self.t, name)


PRICES = [
    {"network": "MTN", "bundle": "1GB", "price": 5.0},
    {"network": "MTN", "bundle": "2GB", "price": 9.5},
    {"network": "MTN", "bundle": "3GB", "price": 14.0},
    {"network": "MTN", "bundle": "5GB", "price": 22.0},
]


@pytest.fixture()
def env(monkeypatch):
    db = FakeDB()
    db.t["prices"] = [dict(p) for p in PRICES]
    monkeypatch.setattr(ds, "_db", lambda: db)
    monkeypatch.setattr(ds, "BUFFER_GHS", 0.0)
    ds._clear_cache()
    ds._price_cache["ts"] = 0.0
    ds._price_cache["map"] = {}
    return db


def set_remote(monkeypatch, value):
    def fake():
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(ds, "fetch_remote_balance", fake)


def test_10_cedis_sells_only_up_to_2gb(env, monkeypatch):
    set_remote(monkeypatch, 10.0)
    assert ds.refresh_balance()["ok"]
    assert ds.bundle_in_stock("MTN", "1GB")
    assert ds.bundle_in_stock("MTN", "2GB")
    assert not ds.bundle_in_stock("MTN", "3GB")
    assert not ds.bundle_in_stock("MTN", "5GB")


def test_buffer_is_kept_back(env, monkeypatch):
    monkeypatch.setattr(ds, "BUFFER_GHS", 2.0)
    set_remote(monkeypatch, 10.0)          # spendable 8.0
    ds.refresh_balance()
    assert ds.bundle_in_stock("MTN", "1GB")
    assert not ds.bundle_in_stock("MTN", "2GB")


def test_topup_restores_stock_and_logs_change(env, monkeypatch):
    set_remote(monkeypatch, 10.0)
    ds.refresh_balance()
    set_remote(monkeypatch, 60.0)
    res = ds.refresh_balance(source="admin:test")
    assert res["changed"] and res["previous_balance"] == 10.0
    assert ds.bundle_in_stock("MTN", "5GB")
    log = env.t["datamart_wallet_log"]
    assert [l["balance"] for l in log] == [10.0, 60.0]
    assert log[1]["delta"] == 50.0 and log[1]["source"] == "admin:test"


def test_unchanged_balance_is_not_logged(env, monkeypatch):
    set_remote(monkeypatch, 10.0)
    ds.refresh_balance()
    ds.refresh_balance()
    assert len(env.t["datamart_wallet_log"]) == 1


def test_never_checked_fails_open(env):
    assert ds.bundle_in_stock("MTN", "5GB")


def test_datamart_failure_keeps_last_balance_then_fails_open_when_stale(env, monkeypatch):
    set_remote(monkeypatch, 10.0)
    ds.refresh_balance()
    set_remote(monkeypatch, RuntimeError("boom"))
    res = ds.refresh_balance()
    assert not res["ok"]
    assert not ds.bundle_in_stock("MTN", "5GB")          # recent reading still trusted
    old = (datetime.now(timezone.utc) - timedelta(seconds=ds.STALE_AFTER_SECONDS + 60)).isoformat()
    env.t["datamart_wallet"][0]["last_ok_at"] = old
    ds._clear_cache()
    assert ds.bundle_in_stock("MTN", "5GB")              # stale -> sell normally
    assert env.t["datamart_wallet"][0]["last_error"] == "boom"


def test_annotate_adds_in_stock_to_any_row_shape(env, monkeypatch):
    set_remote(monkeypatch, 10.0)
    ds.refresh_balance()
    rows = [
        {"network": "MTN", "bundle": "1GB", "final_price": 7.0},     # store/agent shape
        {"network": "MTN", "bundle": "3GB", "final_price": 20.0},
        {"network": "MTN", "bundle": "99GB"},                         # unknown: passes
    ]
    ds.annotate(rows)
    assert [r["in_stock"] for r in rows] == [True, False, True]


def test_reference_is_selling_price_not_agent_cost(env, monkeypatch):
    # 3GB sells at 14.0; an agent's cheaper cost (say 12.0) must not make it "in stock" at 13.0.
    set_remote(monkeypatch, 13.0)
    ds.refresh_balance()
    assert not ds.bundle_in_stock("MTN", "3GB")


def test_admin_status_lists_out_of_stock(env, monkeypatch):
    set_remote(monkeypatch, 10.0)
    ds.refresh_balance()
    st = ds.admin_status()
    assert st["balance"] == 10.0 and st["gating_active"]
    assert [b["bundle"] for b in st["out_of_stock"]] == ["3GB", "5GB"]
    assert st["bundles_total"] == 4


def test_fetch_remote_balance_parses_docs_shape(monkeypatch):
    class R:
        status_code = 200
        text = ""
        def json(self): return {"status": "success", "data": {"balance": 192.50, "currency": "GHS"}}
    monkeypatch.setattr(ds.requests, "get", lambda *a, **k: R())
    assert ds.fetch_remote_balance() == 192.5


def test_purchase_triggers_one_coalesced_recheck(env, monkeypatch):
    import time
    set_remote(monkeypatch, 10.0)
    monkeypatch.setattr(ds, "RECHECK_SETTLE", 0.05)
    monkeypatch.setattr(ds, "RECHECK_MIN_GAP", 0.0)
    ds._recheck_state.update({"last": 0.0, "timer": None})
    calls = []
    real = ds.refresh_balance
    monkeypatch.setattr(ds, "refresh_balance", lambda source="poller": calls.append(source) or real(source))
    monkeypatch.setattr(ds.requests, "post", lambda *a, **k: "resp")
    for _ in range(5):                                   # burst of 5 purchases
        assert ds.purchase_post("https://x/purchase") == "resp"
    time.sleep(0.4)
    assert calls == ["purchase"]                         # coalesced into one check
    assert env.t["datamart_wallet"][0]["balance"] == 10.0


def test_failed_purchase_still_rechecks(env, monkeypatch):
    import time
    monkeypatch.setattr(ds, "RECHECK_SETTLE", 0.05)
    ds._recheck_state.update({"last": 0.0, "timer": None})
    seen = []
    monkeypatch.setattr(ds, "refresh_balance", lambda source="poller": seen.append(source))
    def boom(*a, **k): raise ConnectionError("down")
    monkeypatch.setattr(ds.requests, "post", boom)
    with pytest.raises(ConnectionError):
        ds.purchase_post("https://x/purchase")
    time.sleep(0.3)
    assert seen == ["purchase"]
