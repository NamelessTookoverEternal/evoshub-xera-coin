"""
Paid orders must not sit on "awaiting payment": whoever notices the payment first (webhook, success page,
"my orders", "track order") settles it, and only ONE caller may dispatch it. Fake Supabase, no network.
Run: pytest tests/test_order_payment_settle.py
"""
import os, sys, types
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.getcwd())
for k, v in {"SUPABASE_URL": "https://abc.supabase.co",
             "SUPABASE_SERVICE_ROLE_KEY": "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZSJ9.abc",
             "XERA_TOKEN_SECRET": "y" * 40, "ADMIN_SECRET": "b" * 40}.items():
    os.environ.setdefault(k, v)
import pytest
from services.evosdata import core


class Q:
    def __init__(self, rows):
        self.rows, self.f, self.upd = rows, [], None
    def select(self, *_a): return self
    def update(self, vals): self.upd = vals; return self
    def eq(self, k, v): self.f.append(lambda r: r.get(k) == v); return self
    def in_(self, k, vs): self.f.append(lambda r: r.get(k) in list(vs)); return self
    def is_(self, k, v): self.f.append(lambda r: r.get(k) is None); return self
    def like(self, k, pat):
        pre = pat.rstrip("%"); self.f.append(lambda r: str(r.get(k) or "").startswith(pre)); return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a): return self
    def execute(self):
        hit = [r for r in self.rows if all(f(r) for f in self.f)]
        if self.upd is not None:
            for r in hit: r.update(self.upd)
        return types.SimpleNamespace(data=[dict(r) for r in hit])


class DB:
    def __init__(self, rows): self.rows = rows
    def table(self, _n): return Q(self.rows)


def order(**kw):
    base = {"id": 1, "user_id": 5, "network": "MTN", "bundle": "1GB", "status": "pending_payment",
            "paystack_ref": "EVOS-REF-AAAA", "datamart_ref": None,
            "created_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()}
    base.update(kw)
    return base


@pytest.fixture
def env(monkeypatch):
    rows = [order()]
    calls = {"dispatch": [], "paid": True}
    monkeypatch.setattr(core, "supabase", DB(rows))
    monkeypatch.setattr(core, "_paystack_confirms_paid", lambda ref: calls["paid"])
    monkeypatch.setattr(core, "dispatch_paid_order", lambda o, ref: calls["dispatch"].append(ref) or {"status": "success"})
    monkeypatch.setattr(core.xera_discount, "consume", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "increment_user_orders", lambda *_a: None)
    return rows, calls


def test_paid_order_is_settled_and_dispatched_once(env):
    rows, calls = env
    assert core._settle_if_paid(dict(rows[0])) is True
    assert rows[0]["status"] == "paid" and calls["dispatch"] == ["EVOS-REF-AAAA"]


def test_second_caller_cannot_dispatch_again(env):
    rows, calls = env
    stale = dict(rows[0])                       # both callers read the order while it was still pending
    assert core._settle_if_paid(stale) is True
    assert core._settle_if_paid(stale) is False  # the atomic claim is already taken
    assert len(calls["dispatch"]) == 1


def test_unpaid_order_is_left_alone(env):
    rows, calls = env
    calls["paid"] = False
    assert core._settle_if_paid(dict(rows[0])) is False
    assert rows[0]["status"] == "pending_payment" and not calls["dispatch"]


def test_wallet_paid_and_already_dispatched_orders_are_skipped(env):
    rows, calls = env
    assert core._settle_if_paid(order(paystack_ref="EVOS-WLT-1")) is False
    assert core._settle_if_paid(order(datamart_ref="DM1")) is False
    assert core._settle_if_paid(order(status="processing")) is False
    assert not calls["dispatch"]


def test_old_reference_still_finds_the_reopened_order(env):
    rows, _ = env
    rows[0]["paystack_ref"] = "EVOS-REF-AAAA-R1B2"   # order was re-opened with a newer reference
    assert core._find_order_by_ref("EVOS-REF-AAAA")["id"] == 1
    assert core._find_order_by_ref("EVOS-REF-AAAA-R1B2")["id"] == 1
    assert core._find_order_by_ref("nope%") is None   # wildcard characters never reach the LIKE


def test_heal_checks_only_recent_orders_and_at_most_three(env):
    rows, calls = env
    now = datetime.now(timezone.utc)
    rows.clear()
    rows.extend(order(id=i, paystack_ref=f"R{i}-AAAA", created_at=(now - timedelta(minutes=3)).isoformat()) for i in range(1, 6))
    rows.append(order(id=10, paystack_ref="YOUNG-1234", created_at=now.isoformat()))                         # younger than 10 s
    rows.append(order(id=11, paystack_ref="OLD-12345", created_at=(now - timedelta(hours=7)).isoformat()))   # older than 6 h
    core._heal_pending_orders([dict(r) for r in rows])
    assert len(calls["dispatch"]) == 3
    assert "YOUNG-1234" not in calls["dispatch"] and "OLD-12345" not in calls["dispatch"]
