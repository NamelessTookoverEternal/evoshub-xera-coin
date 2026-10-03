"""
Referral unit tests — HTTP layer only (the SQL functions are exercised in
the Postgres test noted in supabase/tests/). Supabase access is stubbed.
"""

import os
import sys
import types

import pytest

os.environ.setdefault("XERA_TOKEN_SECRET", "test-secret")

# routes_referral imports a module that connects to Supabase at import time.
_fake_xera_supabase = types.ModuleType("utils.xera_supabase")
_fake_xera_supabase.supabase = types.SimpleNamespace()
sys.modules["utils.xera_supabase"] = _fake_xera_supabase

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from utils.rate_limit import limiter
from xera import referrals, routes_auth, routes_referral


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(routes_auth.router, prefix="/api/xera/auth")
    app.include_router(routes_referral.router, prefix="/api/xera/referral")
    limiter.reset()
    return TestClient(app)


@pytest.fixture
def auth_stubs(monkeypatch):
    calls = {"created": [], "linked": []}

    async def no_user(_identifier):
        return None

    async def create(**kw):
        calls["created"].append(kw)
        return {"id": 42, "username": kw["username"], "email": kw["email"], "full_name": kw["full_name"]}

    async def no_owner(_code):
        return None

    async def link(user_id, code, source="xera"):
        calls["linked"].append((user_id, code, source))
        return 7

    monkeypatch.setattr(routes_auth, "get_public_user_by_identifier", no_user)
    monkeypatch.setattr(routes_auth, "create_public_user", create)
    monkeypatch.setattr(routes_auth, "link_referral", link)
    monkeypatch.setattr(referrals, "get_public_user_by_referral_code", no_owner)
    return calls


def _body(**over):
    body = {"username": "kofi_a", "email": "kofi@example.com", "full_name": "Kofi A", "password": "longenough1"}
    body.update(over)
    return body


def test_clean_ref_accepts_every_ecosystem_format():
    assert referrals.clean_ref("EVOS-ABCD-1F3A9C") == "EVOS-ABCD-1F3A9C"   # XERA / EVOSGPT
    assert referrals.clean_ref("kofi_1234") == "kofi_1234"                  # EVOS Data
    assert referrals.clean_ref("  EVOS-ABCD-1234  ") == "EVOS-ABCD-1234"


@pytest.mark.parametrize("bad", ["", None, "ab", "a b", "x;drop", "x,y", "a%b", "a" * 65, "evos\nx"])
def test_clean_ref_rejects_junk(bad):
    assert referrals.clean_ref(bad) is None


def test_mask_username():
    assert referrals.mask_username("kofimensah") == "ko***"
    assert referrals.mask_username("ab") == "a***"
    assert referrals.mask_username(None) == "?***"


def test_new_unique_code_format_and_retry(monkeypatch):
    seen = []

    async def owner(code):
        seen.append(code)
        return {"id": 1} if len(seen) == 1 else None   # first candidate "taken"

    monkeypatch.setattr(referrals, "get_public_user_by_referral_code", owner)
    import asyncio
    code = asyncio.run(referrals.new_unique_code("kofi_a"))
    assert len(seen) == 2 and code == seen[1]
    assert code.startswith("EVOS-KOFI-") and len(code.split("-")[2]) == 6


def test_register_with_ref_links_and_gets_own_code(client, auth_stubs):
    r = client.post("/api/xera/auth/register", json=_body(ref="EVOS-ABCD-1F3A9C"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["referred"] is True
    assert d["referral_code"].startswith("EVOS-KOFI-")
    assert auth_stubs["created"][0]["referral_code"] == d["referral_code"]
    assert auth_stubs["linked"] == [(42, "EVOS-ABCD-1F3A9C", "xera")]


def test_register_without_ref_still_gets_code_and_no_link(client, auth_stubs):
    r = client.post("/api/xera/auth/register", json=_body())
    assert r.status_code == 200
    assert r.json()["referred"] is False
    assert r.json()["referral_code"]
    assert auth_stubs["linked"] == []


def test_register_with_malformed_ref_is_ignored_not_rejected(client, auth_stubs):
    r = client.post("/api/xera/auth/register", json=_body(ref="x;drop table"))
    assert r.status_code == 200
    assert auth_stubs["linked"] == []


def test_register_survives_link_failure(client, auth_stubs, monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(routes_auth, "link_referral", boom)
    r = client.post("/api/xera/auth/register", json=_body(ref="EVOS-ABCD-1F3A9C"))
    assert r.status_code == 200
    assert r.json()["referred"] is False
    assert r.json()["token"]


def test_validate_known_unknown_and_malformed(client, monkeypatch):
    async def owner(code):
        if code.upper() == "EVOS-ABCD-1F3A9C":
            return {"id": 7, "username": "ama", "full_name": "Ama Boateng", "referral_code": "EVOS-ABCD-1F3A9C"}
        return None

    monkeypatch.setattr(routes_referral, "get_public_user_by_referral_code", owner)

    ok = client.get("/api/xera/referral/validate", params={"code": "evos-abcd-1f3a9c"}).json()
    assert ok == {"valid": True, "inviter": "Ama", "code": "EVOS-ABCD-1F3A9C"}   # first name only, no id/email

    assert client.get("/api/xera/referral/validate", params={"code": "EVOS-NOPE-000000"}).json() == {"valid": False}
    assert client.get("/api/xera/referral/validate", params={"code": "bad code!"}).json() == {"valid": False}
    assert client.get("/api/xera/referral/validate").json() == {"valid": False}


def test_me_requires_session(client):
    assert client.get("/api/xera/referral/me").status_code == 401
    assert client.get("/api/xera/referral/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_register_survives_missing_referral_migration(client, auth_stubs, monkeypatch):
    """Code deployed before the SQL migration: RPC missing + column missing."""
    async def rpc_missing(_code):
        raise RuntimeError("Supabase referral lookup failed: 404 function not found")

    created = []

    async def create(**kw):
        if kw.get("referral_code"):
            raise RuntimeError("Supabase user insert failed: 400 column users.referral_code does not exist")
        created.append(kw)
        return {"id": 42, "username": kw["username"], "email": kw["email"], "full_name": kw["full_name"]}

    monkeypatch.setattr(referrals, "get_public_user_by_referral_code", rpc_missing)
    monkeypatch.setattr(routes_auth, "create_public_user", create)
    r = client.post("/api/xera/auth/register", json=_body(ref="EVOS-ABCD-1F3A9C"))
    assert r.status_code == 200, r.text
    assert r.json()["token"] and r.json()["referral_code"] is None
    assert len(created) == 1 and not created[0].get("referral_code")


def test_register_retries_without_code_when_insert_rejects_it(client, auth_stubs, monkeypatch):
    calls = []

    async def create(**kw):
        calls.append(kw.get("referral_code"))
        if kw.get("referral_code"):
            raise RuntimeError("Supabase user insert failed: 400 column users.referral_code does not exist")
        return {"id": 5, "username": kw["username"], "email": kw["email"], "full_name": kw["full_name"]}

    monkeypatch.setattr(routes_auth, "create_public_user", create)
    r = client.post("/api/xera/auth/register", json=_body())
    assert r.status_code == 200
    assert calls[0] and calls[1] is None   # first with a code, then without


def test_unhandled_500_still_carries_cors_headers():
    """Regression: a crashing route used to reach the browser with no CORS header."""
    import importlib
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from fastapi.responses import JSONResponse

    # Mirror main.py's ordering using the real middleware class source.
    src = open(os.path.join(os.path.dirname(__file__), "..", "main.py")).read()
    assert src.index("add_middleware(CatchAllErrorsMiddleware)") < src.index("app.add_middleware(\n    CORSMiddleware")

    class CatchAll(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            try:
                return await call_next(request)
            except Exception:
                return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app = FastAPI()
    app.add_middleware(CatchAll)
    app.add_middleware(CORSMiddleware, allow_origins=["https://evoshub.xyz"], allow_methods=["POST"], allow_headers=["Content-Type"])

    @app.post("/boom")
    def boom():
        raise RuntimeError("x")

    r = TestClient(app, raise_server_exceptions=False).post("/boom", headers={"Origin": "https://evoshub.xyz"})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == "https://evoshub.xyz"


def test_register_always_sends_phone_because_users_phone_is_not_null(client, auth_stubs):
    """Production bug: XERA signup never sent `phone`; users.phone is NOT NULL -> 500."""
    r = client.post("/api/xera/auth/register", json=_body())
    assert r.status_code == 200
    assert auth_stubs["created"][0]["phone"] == ""          # never None

    r = client.post("/api/xera/auth/register", json=_body(username="ama_b", email="ama@example.com", phone="024 123-4567"))
    assert r.status_code == 200
    assert auth_stubs["created"][1]["phone"] == "0241234567"


@pytest.mark.parametrize("bad", ["abc", "123", "024123456789012345"])
def test_register_rejects_malformed_phone(client, auth_stubs, bad):
    assert client.post("/api/xera/auth/register", json=_body(phone=bad)).status_code == 422
    assert auth_stubs["created"] == []


def test_non_referral_insert_errors_are_not_retried(client, auth_stubs, monkeypatch):
    calls = []

    async def create(**kw):
        calls.append(kw)
        raise RuntimeError("Supabase user insert failed: 400 some other not-null violation")

    monkeypatch.setattr(routes_auth, "create_public_user", create)
    with pytest.raises(RuntimeError):
        client.post("/api/xera/auth/register", json=_body())
    assert len(calls) == 1   # no pointless second attempt
