"""
Universal availability policy (services/evosdata/datamart_stock.py). Mocked supplier
responses only: nothing here verifies live DataMart stock.
Run:  pytest tests/evosdata/test_availability.py
"""
import os, sys, types
from datetime import datetime, timedelta, timezone
import pytest

sys.path.insert(0, os.getcwd())
os.environ["DATAMART_API_KEY"] = "test-key"
from services.evosdata import datamart_stock as ds  # noqa: E402


class Q:
    def __init__(s, db, t): s.db, s.t, s.f, s.op, s.p, s.lim = db, t, [], "select", None, None
    def select(s, *a, **k): return s
    def eq(s, c, v): s.f.append(lambda r: r.get(c) == v); return s
    def order(s, *a, **k): return s
    def limit(s, n): s.lim = n; return s
    def insert(s, p): s.op, s.p = "insert", p; return s
    def upsert(s, p): s.op, s.p = "upsert", p; return s
    def execute(s):
        rows = s.db.setdefault(s.t, [])
        if s.op == "insert":
            rows.append(dict(s.p)); return types.SimpleNamespace(data=[s.p])
        if s.op == "upsert":
            for r in rows:
                if r.get("id") == s.p.get("id"): r.update(s.p); break
            else: rows.append(dict(s.p))
            return types.SimpleNamespace(data=[s.p])
        out = [dict(r) for r in rows if all(f(r) for f in s.f)]
        return types.SimpleNamespace(data=out[: s.lim] if s.lim else out)


class DB:
    def __init__(s): s.t = {}
    def table(s, n): return Q(s.t, n)


def iso(dt): return dt.isoformat()


@pytest.fixture()
def env(monkeypatch):
    db = DB()
    db.t["prices"] = []
    db.t["base_prices"] = []
    db.t["provider_routes"] = [{"network": n, "provider": "DATAMART", "priority": 1, "active": True}
                               for n in ("MTN", "TELECEL", "AIRTELTIGO")]
    monkeypatch.setattr(ds, "_db", lambda: db)
    monkeypatch.setattr(ds, "BUFFER_GHS", 0.0)
    monkeypatch.delenv("STOCK_UNKNOWN_BLOCKS_PURCHASE", raising=False)
    reset()
    return db


def reset():
    ds._clear_cache()
    ds._price_cache.update(ts=0.0, map={})
    ds._route_cache.update(ts=0.0, map=None)


def wallet(db, balance, age_s=0):
    ts = iso(datetime.now(timezone.utc) - timedelta(seconds=age_s))
    db.t["datamart_wallet"] = [{"id": 1, "balance": balance, "last_ok_at": ts, "last_checked_at": ts}]
    reset()


def add(db, net, bundle, price, table="prices"):
    db.t[table].append({"network": net, "bundle": bundle, "price": price, "cost_price": price})
    reset()


def status(net, bundle): return ds.bundle_status(net, bundle)


@pytest.mark.parametrize("net,small,large", [("MTN", "1GB", "50GB"), ("TELECEL", "2GB", "100GB"), ("AIRTELTIGO", "1GB", "40GB")])
def test_small_available_large_out_on_every_network(env, net, small, large):
    add(env, net, small, 5); add(env, net, large, 200)
    wallet(env, 20)
    assert status(net, small) == "available"
    assert status(net, large) == "out_of_stock"
    assert ds.bundle_in_stock(net, small) and not ds.bundle_in_stock(net, large)


def test_new_bundle_needs_no_rule(env):
    wallet(env, 20)
    add(env, "MTN", "77GB", 999)          # added after "deployment"
    assert status("MTN", "77GB") == "out_of_stock"


def test_background_price_update_is_picked_up(env):
    add(env, "MTN", "10GB", 40); wallet(env, 30)
    assert status("MTN", "10GB") == "out_of_stock"
    env.t["prices"][0]["price"] = 25; reset()
    assert status("MTN", "10GB") == "available"


def test_restock_restores_bundle(env):
    add(env, "MTN", "10GB", 40)
    wallet(env, 10); assert status("MTN", "10GB") == "out_of_stock"
    wallet(env, 100); assert status("MTN", "10GB") == "available"


def test_agent_only_bundle_in_base_prices_is_gated(env):
    add(env, "MTN", "30GB", 120, table="base_prices")   # no retail row
    wallet(env, 20)
    assert status("MTN", "30GB") == "out_of_stock"


def test_higher_of_two_tables_wins(env):
    add(env, "MTN", "5GB", 20); add(env, "MTN", "5GB", 30, table="base_prices")
    wallet(env, 25)
    assert status("MTN", "5GB") == "out_of_stock"


@pytest.mark.parametrize("net,bundle", [("at", "40 gb"), ("AT", "40GB"), ("Airtel Tigo", "40GB"), ("airteltigo", "40Gb")])
def test_aliases_and_formats_match(env, net, bundle):
    add(env, "AIRTELTIGO", "40GB", 150); wallet(env, 20)
    assert status(net, bundle) == "out_of_stock"


def test_vodafone_alias_maps_to_telecel(env):
    add(env, "TELECEL", "20GB", 90); wallet(env, 20)
    assert status("Vodafone", "20GB") == "out_of_stock"


def test_unknown_bundle_is_unknown_not_available(env):
    wallet(env, 20)
    assert status("MTN", "999GB") == "unknown"
    assert ds.bundle_in_stock("MTN", "999GB")   # default: shop keeps selling


def test_stale_supplier_data_is_unknown(env):
    add(env, "MTN", "50GB", 200); wallet(env, 5, age_s=ds.STALE_AFTER_SECONDS + 60)
    assert status("MTN", "50GB") == "unknown"


def test_supplier_timeout_does_not_mark_out_of_stock(env, monkeypatch):
    add(env, "MTN", "50GB", 200)
    monkeypatch.setattr(ds, "fetch_remote_balance", lambda: (_ for _ in ()).throw(TimeoutError("t/o")))
    assert ds.refresh_balance()["ok"] is False
    assert status("MTN", "50GB") == "unknown"


def test_malformed_response_does_not_mark_out_of_stock(env, monkeypatch):
    add(env, "MTN", "50GB", 200)
    class R:
        status_code = 200
        text = "<html>"
        def json(self): return {"status": "success", "data": {}}
    monkeypatch.setattr(ds.requests, "get", lambda *a, **k: R())
    assert ds.refresh_balance()["ok"] is False
    assert status("MTN", "50GB") == "unknown"


def test_unknown_blocks_purchase_when_switch_on(env, monkeypatch):
    wallet(env, 20)
    monkeypatch.setenv("STOCK_UNKNOWN_BLOCKS_PURCHASE", "true")
    assert not ds.bundle_in_stock("MTN", "999GB")


def test_fallback_provider_does_not_mask_out_of_stock(env):
    # DataMart is first choice; a lower-priority fallback must not hide a wallet shortfall.
    add(env, "MTN", "50GB", 200); wallet(env, 5)
    env.t["provider_routes"].append({"network": "MTN", "provider": "SWIFT_DATA_LINK", "priority": 2, "active": True})
    reset()
    assert status("MTN", "50GB") == "out_of_stock"


def test_non_datamart_primary_is_not_gated_by_wallet(env):
    add(env, "MTN", "50GB", 200); wallet(env, 5)
    env.t["provider_routes"].append({"network": "MTN", "provider": "SWIFT_DATA_LINK", "priority": 0, "active": True})
    reset()
    assert status("MTN", "50GB") == "available"


def test_inactive_fallback_provider_ignored(env):
    add(env, "MTN", "50GB", 200); wallet(env, 5)
    env.t["provider_routes"].append({"network": "MTN", "provider": "SWIFT_DATA_LINK", "priority": 2, "active": False})
    reset()
    assert status("MTN", "50GB") == "out_of_stock"


def test_annotate_agrees_with_guard_and_admin(env):
    for net in ("MTN", "TELECEL", "AIRTELTIGO"):
        add(env, net, "1GB", 5); add(env, net, "60GB", 300)
    wallet(env, 20)
    rows = ds.annotate([{"network": n, "bundle": b} for n in ("MTN", "Vodafone", "AT") for b in ("1GB", "60GB")])
    for r in rows:
        assert r["in_stock"] == ds.bundle_in_stock(r["network"], r["bundle"])
        assert r["stock_status"] == status(r["network"], r["bundle"])
    out = {(o["network"], o["bundle"]) for o in ds.admin_status()["out_of_stock"]}
    assert out == {("MTN", "60GB"), ("TELECEL", "60GB"), ("AIRTELTIGO", "60GB")}
