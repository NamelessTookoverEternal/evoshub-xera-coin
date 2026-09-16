"""
Test harness stub for `main` (the real module boots a live FastAPI app +
real Supabase client, which needs env vars/network we don't want in unit
tests). Chain-layer unit tests exercise the actual cryptography
(EIP-712 signing/recovery, TON Ed25519 proof verification) against a
fake-but-behaviorally-realistic Supabase client, never mocking the crypto
itself.
"""

import sys
import types

import pytest


class FakeTable:
    """Minimal chainable stand-in for supabase-py's table query builder."""

    def __init__(self, store, name):
        self.store = store
        self.name = name
        self._filters = []
        self._select = "*"
        self._limit = None
        self._order = None

    def select(self, *_a, **_kw):
        return self

    def eq(self, key, value):
        self._filters.append((key, value))
        return self

    def is_(self, key, value):
        self._filters.append((key, None if value in ("null", None) else value))
        return self

    def order(self, *_a, **_kw):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, *_a, **_kw):
        return self

    def _matches(self, row):
        return all(row.get(k) == v for k, v in self._filters)

    def execute(self):
        rows = [r for r in self.store.setdefault(self.name, []) if self._matches(r)]
        if self._limit:
            rows = rows[: self._limit]
        return types.SimpleNamespace(data=rows, count=len(rows))

    def insert(self, row):
        table = self.store.setdefault(self.name, [])
        row = dict(row)
        row.setdefault("id", len(table) + 1)
        table.append(row)
        return _Result([row])

    def update(self, patch):
        return _UpdateBuilder(self.store, self.name, patch)


class _UpdateBuilder:
    """supabase-py's real chain is `.update(patch).eq(...).eq(...).execute()`
    — filters are applied AFTER `.update()`, not before. This mirrors that:
    it accumulates filters itself and only touches rows on `.execute()`."""

    def __init__(self, store, name, patch):
        self.store = store
        self.name = name
        self.patch = patch
        self._filters = []

    def eq(self, key, value):
        self._filters.append((key, value))
        return self

    def is_(self, key, value):
        self._filters.append((key, None if value in ("null", None) else value))
        return self

    def _matches(self, row):
        return all(row.get(k) == v for k, v in self._filters)

    def execute(self):
        table = self.store.setdefault(self.name, [])
        updated = []
        for row in table:
            if self._matches(row):
                row.update(self.patch)
                updated.append(row)
        return _Result(updated)


class _Result:
    """supabase-py's `.insert(...)`/`.update(...)` already return the final
    result synchronously in this fake (no separate `.execute()` needed for
    them in the real client either, but callers in this codebase always
    chain `.execute()` out of habit/consistency) — this small wrapper lets
    both `res.data` and `res.execute().data` work."""

    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class FakeSupabase:
    """In-memory fake with the handful of RPCs the chain layer calls."""

    def __init__(self):
        self.store: dict[str, list[dict]] = {}
        self.rpc_handlers = {}

    def table(self, name):
        return FakeTable(self.store, name)

    def rpc(self, name, params):
        if name not in self.rpc_handlers:
            raise RuntimeError(f"unstubbed rpc: {name}")
        result = self.rpc_handlers[name](params)
        # Real supabase-py's .rpc(...) needs a trailing .execute() before the
        # result is usable; test-authored handlers often just return
        # SimpleNamespace(data=...) for brevity, so make that chainable too.
        if not hasattr(result, "execute"):
            result = _Result(getattr(result, "data", result))
        return result


class FakeLimiter:
    def limit(self, *_a, **_kw):
        def deco(fn):
            return fn
        return deco


# Installed at COLLECTION time (module import), not inside a fixture —
# xera.chain.config does `from main import supabase` at import time, and
# test modules import xera.chain.* at module level too, both of which run
# before any per-test fixture would get a chance to stub `main` first.
# Without this, Python would resolve the real project `main.py` (it's on
# sys.path as a top-level module) and drag in the whole live app (real
# Supabase client, admin auth, etc.) just to unit-test the chain layer.
sys.modules["main"] = types.ModuleType("main")
sys.modules["main"].limiter = FakeLimiter()
sys.modules["main"].supabase = FakeSupabase()  # default instance; per-test fixture below swaps it out


@pytest.fixture
def fake_supabase():
    fake = FakeSupabase()
    sys.modules["main"].supabase = fake

    # Chain modules cache `from main import supabase` at import time, so any
    # module already imported in a previous test needs a fresh import here
    # to pick up this test's fake instance.
    for mod in list(sys.modules):
        if mod.startswith("xera.chain") or mod == "xera.routes_chain":
            del sys.modules[mod]

    return fake
