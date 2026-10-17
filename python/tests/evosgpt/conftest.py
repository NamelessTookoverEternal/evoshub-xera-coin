"""Shared fixtures for the EVOSGPT tests: a tiny in-memory stand-in for Supabase + the `env` fixture."""
import os
import sys
import types

import pytest

os.environ.setdefault("XERA_TOKEN_SECRET", "test-secret-for-evosgpt")


class _Q:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.f, self.op, self.payload, self._limit, self._order = [], "select", None, None, None

    def select(self, *a, **k): return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def or_(self, expr):
        pairs = [p.split(".eq.") for p in expr.split(",")]
        self.f.append(("__or__", pairs)); return self
    def order(self, key, desc=False, **k): self._order = (key, desc); return self
    def lt(self, k, v): self.f.append((k, ("lt", v))); return self
    def in_(self, k, vals): self.f.append((k, ("in", list(vals)))); return self
    def limit(self, n): self._limit = n; return self
    def insert(self, row): self.op, self.payload = "insert", row; return self
    def update(self, row): self.op, self.payload = "update", row; return self
    def delete(self): self.op = "delete"; return self

    def _match(self, r):
        for k, v in self.f:
            if k == "__or__":
                if not any(str(r.get(a)) == b for a, b in v): return False
            elif isinstance(v, tuple) and v and v[0] == "lt":
                if r.get(k) is None or not str(r.get(k)) < str(v[1]): return False
            elif isinstance(v, tuple) and v and v[0] == "in":
                if r.get(k) not in v[1]: return False
            elif r.get(k) != v: return False
        return True

    def execute(self):
        rows = self.db.setdefault(self.name, [])
        if self.op == "insert":
            row = dict(self.payload); row.setdefault("id", len(rows) + 1); rows.append(row)
            return types.SimpleNamespace(data=[row], count=1)
        hits = [r for r in rows if self._match(r)]
        if self._order:
            key, desc = self._order
            hits.sort(key=lambda r: (r.get(key) is None, str(r.get(key))), reverse=desc)
        if self.op == "update":
            for r in hits: r.update(self.payload)
        elif self.op == "delete":
            for r in hits: rows.remove(r)
        if self._limit: hits = hits[: self._limit]
        return types.SimpleNamespace(data=hits, count=len(hits))


class FakeDB:
    def __init__(self): self.t = {}
    def table(self, name): return _Q(self.t, name)


@pytest.fixture()
def env(monkeypatch):
    fake = FakeDB()
    import services.evosdata.db as dbmod
    monkeypatch.setattr(dbmod, "get_supabase", lambda: fake)
    for m in [m for m in sys.modules if m.startswith("services.evosgpt")]:
        del sys.modules[m]
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.evosgpt import core
    from utils.rate_limit import limiter
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(core.router, prefix="/api/evosgpt")
    fake.t["users"] = [
        {"id": 1, "username": "ama", "email": "ama@x.com", "full_name": "Ama", "evosgpt_tier": "Basic",
         "password": core.hash_password("secret12"), "referral_code": "EVOS-AMA-1"},
        {"id": 2, "username": "kofi", "email": "kofi@x.com", "full_name": "Kofi", "evosgpt_tier": "Basic",
         "password": core.hash_password("secret12"), "referral_code": "EVOS-KOF-2"},
    ]
    return types.SimpleNamespace(core=core, db=fake, client=TestClient(app), monkeypatch=monkeypatch)


