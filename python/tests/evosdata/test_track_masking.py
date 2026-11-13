"""Tracking by phone number: delivery time for everyone, amount + reference only for the signed-in owner."""
import sys
from types import SimpleNamespace
import pytest

core = pytest.importorskip("services.evosdata.core")


class _Q:
    def __init__(s, rows): s.rows = rows; s.not_ = s
    def select(s, *a): return s
    def eq(s, *a): return s
    def is_(s, *a): return s
    def gte(s, *a): return s
    def order(s, *a, **k): return s
    def limit(s, *a): return s
    def execute(s): return SimpleNamespace(data=[dict(r) for r in s.rows])


class _DB:
    def __init__(s, rows): s.rows = rows
    def table(s, n): return _Q(s.rows)


ROW = {"user_id": 7, "network": "MTN", "bundle": "1GB", "price": 5.5, "phone_number": "0240000000",
       "status": "successful", "created_at": "2026-11-13T10:30:00+00:00", "delivered_at": "2026-11-13T11:00:00+00:00",
       "evosdata_ref": "EVOS-ABC", "paystack_ref": "PS-123"}


def _req(token=""):
    return SimpleNamespace(headers={"X-User-Token": token} if token else {})


def _run(monkeypatch, token):
    monkeypatch.setattr(core, "supabase", _DB([ROW]))
    fn = core.track_orders
    fn = getattr(fn, "__wrapped__", fn)        # skip the rate limiter
    return fn(_req(token), phone="0240000000")["orders"][0]


def test_guest_sees_delivery_time_but_not_amount_or_reference(monkeypatch):
    o = _run(monkeypatch, "")
    assert o["delivered_at"] and o["masked"] is True
    assert o["price"] is None and o["evosdata_ref"] == "***" and o["paystack_ref"] == "***"
    assert "user_id" not in o


def test_owner_sees_everything(monkeypatch):
    o = _run(monkeypatch, core.make_user_token(7))
    assert o["masked"] is False and o["price"] == 5.5 and o["evosdata_ref"] == "EVOS-ABC"


def test_someone_elses_token_stays_masked(monkeypatch):
    o = _run(monkeypatch, core.make_user_token(8))
    assert o["masked"] is True and o["paystack_ref"] == "***"
