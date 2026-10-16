"""Hub session -> EVOS Data authorization (merged backend). No network, fake Supabase."""
import os
import types

for k, v in {
    "SUPABASE_URL": "https://abc.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZSJ9.abc",
    "XERA_TOKEN_SECRET": "y" * 40,
    "ADMIN_SECRET": "b" * 40,
}.items():
    os.environ.setdefault(k, v)

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.evosdata import mount_evosdata
from services.evosdata import core
from utils.rate_limit import limiter
from xera.user_auth import make_user_token as hub_token

USERS = {
    1: {"id": 1, "username": "cust", "email": "c@x.com", "role": "user", "agent_status": "pending"},
    2: {"id": 2, "username": "agt", "email": "a@x.com", "role": "agent", "agent_status": "approved"},
    3: {"id": 3, "username": "pend", "email": "p@x.com", "role": "agent", "agent_status": "pending"},
}


class _Q:
    def __init__(self, uid=None): self.uid = uid
    def select(self, *a, **k): return self
    def eq(self, col, val):
        if col == "id": self.uid = int(val)
        return self
    def limit(self, *a): return self
    def execute(self):
        row = USERS.get(self.uid)
        return types.SimpleNamespace(data=[row] if row else [])


class _SB:
    def table(self, name): return _Q()


@pytest.fixture(scope="module")
def client():
    core.supabase = _SB()
    app = FastAPI()
    app.state.limiter = limiter
    mount_evosdata(app)
    return TestClient(app)


def test_hub_session_customer(client):
    r = client.post("/api/evosdata/auth/hub-session", headers={"Authorization": "Bearer " + hub_token(1)})
    assert r.status_code == 200
    u = r.json()["user"]
    assert u["id"] == 1 and u["agent_token"] is None and u["user_token"]


def test_hub_session_agent_only_if_approved(client):
    ok = client.post("/api/evosdata/auth/hub-session", headers={"Authorization": "Bearer " + hub_token(2)}).json()["user"]
    pend = client.post("/api/evosdata/auth/hub-session", headers={"Authorization": "Bearer " + hub_token(3)}).json()["user"]
    assert ok["agent_token"] and not pend["agent_token"]


@pytest.mark.parametrize("hdr", [{}, {"Authorization": "Bearer abc.def"}, {"Authorization": "Bearer "}])
def test_hub_session_rejects_bad_tokens(client, hdr):
    assert client.post("/api/evosdata/auth/hub-session", headers=hdr).status_code == 401


def test_hub_session_unknown_user(client):
    assert client.post("/api/evosdata/auth/hub-session", headers={"Authorization": "Bearer " + hub_token(999)}).status_code == 401


def test_user_and_agent_verifiers_accept_hub_token_only_for_own_id(client):
    assert core.verify_user_token(hub_token(1), 1)
    assert not core.verify_user_token(hub_token(1), 2)          # other user's id
    assert core.verify_agent_token(hub_token(2), 2)              # approved agent
    assert not core.verify_agent_token(hub_token(2), 1)          # wrong id
    assert not core.verify_agent_token(hub_token(1), 1)          # customer is not an agent
    assert not core.verify_agent_token(hub_token(3), 3)          # agent not yet approved
    assert not core.verify_agent_token("garbage", 2)


def test_legacy_evosdata_tokens_still_work(client):
    assert core.verify_user_token(core.make_user_token(1), 1)
    assert core.verify_agent_token(core.make_agent_token(2), 2)
    assert not core.verify_user_token(core.make_user_token(1), 2)


def test_agent_route_requires_valid_token(client):
    assert client.get("/api/evosdata/agent/wallet/2").status_code == 403
    assert client.get("/api/evosdata/agent/wallet/2", headers={"X-Agent-Token": hub_token(1)}).status_code == 403


def test_webhook_aliases_registered_at_both_paths(client):
    paths = {getattr(r, "path", "") for r in client.app.routes}
    for p in ("/webhook/paystack", "/api/evosdata/webhook/paystack", "/webhook/moolre", "/api/evosdata/webhook/datamart"):
        assert p in paths


def test_paystack_webhook_rejects_bad_signature_on_both_paths(client):
    for p in ("/webhook/paystack", "/api/evosdata/webhook/paystack"):
        r = client.post(p, content=b"{}", headers={"x-paystack-signature": "bad"})
        # Existing behaviour, preserved: 200 + "invalid signature", and nothing is processed.
        assert r.json() == {"status": "invalid signature"}, (p, r.status_code, r.text)


def test_callback_base_allowlist():
    from starlette.requests import Request
    def req(o): return Request({"type": "http", "headers": [(b"origin", o.encode())] if o else []})
    assert core.callback_base(req("https://evoshub.xyz")) == "https://evoshub.xyz/evosdata"
    assert core.callback_base(req("https://evil.example")) == "https://evosdata.xyz"
    assert core.callback_base(req("")) == "https://evosdata.xyz"


def test_background_jobs_toggle(monkeypatch):
    app_on, app_off = FastAPI(), FastAPI()
    monkeypatch.setenv("EVOSDATA_BACKGROUND_JOBS", "true")
    mount_evosdata(app_on)
    monkeypatch.setenv("EVOSDATA_BACKGROUND_JOBS", "false")
    mount_evosdata(app_off)
    assert len(app_on.router.on_startup) >= 1 and len(app_off.router.on_startup) == 0
    monkeypatch.setenv("EVOSDATA_ENABLED", "false")
    app_dis = FastAPI()
    assert mount_evosdata(app_dis) is False and not any(getattr(r, "path", "").startswith("/api/evosdata") for r in app_dis.routes)


# ---- per-user endpoints that used to trust a bare user_id --------------------
_PRIVATE = ["/api/evosdata/orders/me?user_id=1", "/api/evosdata/users/me?user_id=1", "/api/evosdata/today/1"]


@pytest.mark.parametrize("path", _PRIVATE)
def test_private_endpoints_reject_anonymous(client, path):
    assert client.get(path).status_code == 403


@pytest.mark.parametrize("path", _PRIVATE)
def test_private_endpoints_reject_garbage_and_other_users_token(client, path):
    assert client.get(path, headers={"X-User-Token": "garbage"}).status_code == 403
    assert client.get(path, headers={"X-User-Token": hub_token(2)}).status_code == 403      # user 2 reading user 1
    assert client.get(path, headers={"X-User-Token": hub_token(1, )[:-3] + "xxx"}).status_code == 403  # tampered


@pytest.mark.parametrize("path", _PRIVATE)
def test_private_endpoints_reject_expired_token(client, path):
    assert client.get(path, headers={"X-User-Token": core.make_user_token(1, ttl=-5)}).status_code == 403


def test_private_endpoints_accept_own_token(client):
    assert client.get(_PRIVATE[0], headers={"X-User-Token": hub_token(1)}).status_code == 200
    assert client.get(_PRIVATE[0], headers={"X-User-Token": core.make_user_token(1)}).status_code == 200
    for p in _PRIVATE[1:]:
        assert client.get(p, headers={"X-User-Token": hub_token(1)}).status_code != 403
