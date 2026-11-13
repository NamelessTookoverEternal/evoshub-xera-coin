from datetime import datetime, timedelta, timezone
import pytest
eta = pytest.importorskip("services.evosdata.delivery_eta")

def test_bands_follow_recent_speed():
    assert "10 - 30" in eta.estimate_text(30)           # delivered in 30 min -> 10-30 min message
    assert "1 - 2 hours" in eta.estimate_text(90)       # slower deliveries -> 1-2 hours
    assert "4 hours" in eta.estimate_text(150)          # over 2h -> validation message

def test_late_order_moves_up_a_band():
    assert "4 hours" in eta.estimate_text(20, waited_minutes=200)
    assert "1 - 2 hours" in eta.estimate_text(20, waited_minutes=100)

class _Q:
    def __init__(s, rows): s.rows = rows; s.not_ = s
    def select(s,*a): return s
    def eq(s,*a): return s
    def is_(s,*a): return s
    def gte(s,*a): return s
    def order(s,*a,**k): return s
    def limit(s,*a): return s
    def execute(s): return type("R", (), {"data": s.rows})()
class _DB:
    def __init__(s, rows): s.rows = rows
    def table(s, n): return _Q(s.rows)

def test_median_and_default():
    now = datetime.now(timezone.utc)
    mk = lambda m: {"created_at": (now - timedelta(minutes=m + 5)).isoformat(), "delivered_at": (now - timedelta(minutes=5)).isoformat()}
    assert round(eta.recent_typical_minutes(_DB([mk(100), mk(110), mk(95)]), "MTN", now)) == 100
    assert eta.recent_typical_minutes(_DB([mk(100)]), "MTN", now) == eta.DEFAULT_MINUTES   # too few samples

def test_enrich_only_pending_orders():
    now = datetime.now(timezone.utc)
    rows = [{"network": "MTN", "status": "processing", "created_at": now.isoformat()},
            {"network": "MTN", "status": "successful", "created_at": now.isoformat()}]
    out = eta.enrich(_DB([]), rows, now)
    assert "eta_text" in out[0] and "eta_text" not in out[1]
