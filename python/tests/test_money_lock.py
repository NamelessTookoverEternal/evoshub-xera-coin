"""
Money lock guard (xera/money_lock.py): locked accounts are refused on the send and withdraw paths, unlocked or
unknown accounts pass, a missing table (migration not applied) does not break anything, and any other lookup
error fails CLOSED. Supabase is an in-memory fake; the SQL (scan/unlock) was tested separately on Postgres.
"""
import pytest
from fastapi import HTTPException

from xera import money_lock


class _Res:
    def __init__(self, data): self.data = data


class _Table:
    def __init__(self, rows, boom): self.rows, self.boom, self.uid = rows, boom, None
    def select(self, *_a, **_k): return self
    def eq(self, key, val): self.uid = val; return self
    def limit(self, *_a): return self
    def execute(self):
        if self.boom: raise self.boom
        return _Res([r for r in self.rows if r["user_id"] == self.uid])


class _Fake:
    def __init__(self, rows=(), boom=None): self.rows, self.boom = list(rows), boom
    def table(self, _name): return _Table(self.rows, self.boom)


def _use(monkeypatch, **kw):
    monkeypatch.setattr(money_lock, "supabase", _Fake(**kw))


def test_locked_user_is_refused_with_support_message(monkeypatch):
    _use(monkeypatch, rows=[{"user_id": 7, "locked": True}])
    with pytest.raises(HTTPException) as e:
        money_lock.ensure_not_locked(7)
    assert e.value.status_code == 403 and "Contact support" in e.value.detail


def test_unlocked_and_unknown_users_pass(monkeypatch):
    _use(monkeypatch, rows=[{"user_id": 7, "locked": False}])
    money_lock.ensure_not_locked(7)
    money_lock.ensure_not_locked(8)


def test_missing_table_means_nothing_is_locked(monkeypatch):
    _use(monkeypatch, boom=Exception('relation "xera_money_locks" does not exist'))
    assert money_lock.is_locked(1) is False


def test_other_errors_fail_closed(monkeypatch):
    _use(monkeypatch, boom=Exception("connection reset"))
    with pytest.raises(HTTPException) as e:
        money_lock.is_locked(1)
    assert e.value.status_code == 503
