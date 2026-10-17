"""EVOSGPT inside the Hub: auth, currency, payments. No network, no real Supabase/OpenAI/Paystack."""
import os
import sys
import types

import pytest

os.environ.setdefault("XERA_TOKEN_SECRET", "test-secret-for-evosgpt")


class _Q:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.f, self.op, self.payload, self._limit = [], "select", None, None

    def select(self, *a, **k): return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def or_(self, expr):
        pairs = [p.split(".eq.") for p in expr.split(",")]
        self.f.append(("__or__", pairs)); return self
    def order(self, *a, **k): return self
    def limit(self, n): self._limit = n; return self
    def insert(self, row): self.op, self.payload = "insert", row; return self
    def update(self, row): self.op, self.payload = "update", row; return self
    def delete(self): self.op = "delete"; return self

    def _match(self, r):
        for k, v in self.f:
            if k == "__or__":
                if not any(str(r.get(a)) == b for a, b in v): return False
            elif r.get(k) != v: return False
        return True

    def execute(self):
        rows = self.db.setdefault(self.name, [])
        if self.op == "insert":
            row = dict(self.payload); row.setdefault("id", len(rows) + 1); rows.append(row)
            return types.SimpleNamespace(data=[row], count=1)
        hits = [r for r in rows if self._match(r)]
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


def _hdr(core, uid):
    return {"Authorization": f"Bearer {core.make_user_token(uid)}"}


def test_company_name_is_evoxera_technology(env):
    assert "Evoxera Technology" in env.core.BASE_PROMPT
    assert "EVOS Technologies" not in env.core.BASE_PROMPT


def test_login_issues_a_hub_session_token(env):
    r = env.client.post("/api/evosgpt/auth/login", json={"username": "ama", "password": "secret12"}).json()
    assert r["status"] == "ok" and r["user"]["id"] == 1
    assert env.core.verify_user_token(r["user"]["user_token"]) == 1


def test_login_rejects_filter_injection_and_bad_password(env):
    r = env.client.post("/api/evosgpt/auth/login", json={"username": "ama,password.neq.x", "password": "x"}).json()
    assert r["status"] == "invalid_credentials"
    r = env.client.post("/api/evosgpt/auth/login", json={"username": "ama", "password": "wrong"}).json()
    assert r["status"] == "invalid_credentials"


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/evosgpt/user/1", None),
    ("get", "/api/evosgpt/memory/1", None),
    ("delete", "/api/evosgpt/memory/1", None),
    ("get", "/api/evosgpt/referral/1", None),
    ("post", "/api/evosgpt/chat", {"user_id": 1, "message": "hi"}),
    ("post", "/api/evosgpt/coupon/redeem", {"user_id": 1, "code": "EVOSPRO2026"}),
    ("post", "/api/evosgpt/upgrade/init", {"user_id": 1, "tier": "Pro", "email": "a@b.c"}),
])
def test_user_routes_need_a_token(env, method, path, body):
    r = getattr(env.client, method)(path, **({"json": body} if body else {}))
    assert r.status_code == 403


def test_token_for_another_user_is_refused(env):
    r = env.client.get("/api/evosgpt/user/1", headers=_hdr(env.core, 2))
    assert r.status_code == 403
    r = env.client.post("/api/evosgpt/chat", json={"user_id": 1, "message": "hi"}, headers=_hdr(env.core, 2))
    assert r.status_code == 403


def test_own_token_works_for_user_and_chat(env):
    env.monkeypatch.setattr(env.core, "call_openai", lambda *a, **k: "Hello Ama")
    env.monkeypatch.setattr(env.core, "get_geo_context", lambda req: {"country_code": "GH", "local_time": "now", "timezone": "UTC"})
    assert env.client.get("/api/evosgpt/user/1", headers=_hdr(env.core, 1)).status_code == 200
    r = env.client.post("/api/evosgpt/chat", json={"user_id": 1, "message": "hi"}, headers=_hdr(env.core, 1)).json()
    assert r["status"] == "ok" and r["reply"] == "Hello Ama"


def test_hub_session_exchange(env):
    ok = env.client.post("/api/evosgpt/auth/hub-session", headers=_hdr(env.core, 1))
    assert ok.status_code == 200 and ok.json()["user"]["username"] == "ama"
    bad = env.client.post("/api/evosgpt/auth/hub-session", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


# ---- currency -------------------------------------------------------------
def test_currency_defaults_to_ghs_for_ghana_and_unknown(env):
    for q in ("?country=GH", "?country=ZZ"):
        r = env.client.get("/api/evosgpt/currency" + q).json()
        assert r["currency"] == "GHS" and r["rate"] == 1.0 and r["converted"] is False


def test_currency_follows_visitor_country_when_rates_exist(env):
    import services.evosgpt.currency as cur
    env.monkeypatch.setattr(cur, "_load_rates", lambda: {"USD": 0.09, "EUR": 0.08, "NGN": 140.0})
    us = env.client.get("/api/evosgpt/currency?country=us").json()
    assert (us["currency"], us["rate"], us["converted"]) == ("USD", 0.09, True)
    assert env.client.get("/api/evosgpt/currency?country=DE").json()["currency"] == "EUR"
    assert env.client.get("/api/evosgpt/currency?country=NG").json()["currency"] == "NGN"
    assert us["tiers_ghs"] == {"Pro": 20, "Core": 70}


def test_currency_never_invents_a_rate(env):
    import services.evosgpt.currency as cur
    env.monkeypatch.setattr(cur, "_load_rates", lambda: None)
    r = env.client.get("/api/evosgpt/currency?country=US").json()
    assert r["currency"] == "GHS" and r["rate"] == 1.0


def test_currency_uses_ip_lookup_when_no_country_given(env):
    import services.evosgpt.currency as cur
    env.monkeypatch.setattr(cur, "_load_rates", lambda: {"USD": 0.09})
    env.monkeypatch.setattr(env.core, "get_geo_context", lambda req: {"country_code": "US"})
    assert env.client.get("/api/evosgpt/currency").json()["currency"] == "USD"


def test_system_prompt_carries_visitor_currency(env):
    import services.evosgpt.currency as cur
    env.monkeypatch.setattr(cur, "_load_rates", lambda: {"USD": 0.09})
    p = env.core.build_system_prompt("Basic", None, "ama", {"country_code": "US"})
    assert "local currency is USD" in p
    assert "local currency is GHS" in env.core.build_system_prompt("Basic", None, "ama", None)


# ---- payments -------------------------------------------------------------
class _Resp:
    def __init__(self, data): self._d = data
    def json(self): return self._d


def _purchase(env, ref="EVOS-GPT-1-ABCDEF12", tier="Pro", status="pending"):
    env.db.t.setdefault("evosgpt_purchases", []).append({"user_id": 1, "tier": tier, "reference": ref, "status": status})
    return ref


def test_verify_upgrades_after_paystack_confirms(env):
    env.core.PAYSTACK_SECRET = "sk_test"
    ref = _purchase(env)
    env.monkeypatch.setattr(env.core.requests, "get", lambda *a, **k: _Resp(
        {"status": True, "data": {"status": "success", "currency": "GHS", "amount": 2000}}))
    r = env.client.get(f"/api/evosgpt/upgrade/verify/{ref}", headers=_hdr(env.core, 1)).json()
    assert r["paid"] is True and r["tier"] == "Pro"
    assert env.db.t["users"][0]["evosgpt_tier"] == "Pro"
    assert env.db.t["evosgpt_purchases"][0]["status"] == "paid"


def test_verify_refuses_underpayment_wrong_currency_and_other_users(env):
    env.core.PAYSTACK_SECRET = "sk_test"
    ref = _purchase(env, tier="Core")
    env.monkeypatch.setattr(env.core.requests, "get", lambda *a, **k: _Resp(
        {"status": True, "data": {"status": "success", "currency": "GHS", "amount": 2000}}))   # paid 20, Core is 70
    assert env.client.get(f"/api/evosgpt/upgrade/verify/{ref}", headers=_hdr(env.core, 1)).json()["paid"] is False
    env.monkeypatch.setattr(env.core.requests, "get", lambda *a, **k: _Resp(
        {"status": True, "data": {"status": "success", "currency": "USD", "amount": 99999}}))
    assert env.client.get(f"/api/evosgpt/upgrade/verify/{ref}", headers=_hdr(env.core, 1)).json()["paid"] is False
    assert env.client.get(f"/api/evosgpt/upgrade/verify/{ref}", headers=_hdr(env.core, 2)).status_code == 403
    assert env.db.t["users"][0]["evosgpt_tier"] == "Basic"


def test_verify_rejects_malformed_reference(env):
    assert env.client.get("/api/evosgpt/upgrade/verify/../../x", headers=_hdr(env.core, 1)).status_code in (404, 400)
    assert env.client.get("/api/evosgpt/upgrade/verify/bad-ref", headers=_hdr(env.core, 1)).status_code == 400


def test_webhook_signature_and_idempotency(env):
    import hashlib, hmac, json
    env.core.PAYSTACK_SECRET = "sk_test"
    ref = _purchase(env)
    body = json.dumps({"event": "charge.success", "data": {"reference": ref, "metadata": {"user_id": 1, "tier": "Pro"}}}).encode()
    sig = hmac.new(b"sk_test", body, hashlib.sha512).hexdigest()
    bad = env.client.post("/api/evosgpt/webhook/evosgpt-paystack", content=body, headers={"x-paystack-signature": "x"}).json()
    assert bad["status"] == "invalid_signature"
    ok = env.client.post("/api/evosgpt/webhook/evosgpt-paystack", content=body, headers={"x-paystack-signature": sig}).json()
    again = env.client.post("/api/evosgpt/webhook/paystack", content=body, headers={"x-paystack-signature": sig}).json()
    assert ok["status"] == "success" and again["status"] == "already_processed"


def test_webhook_cannot_grant_founder_tier(env):
    import hashlib, hmac, json
    env.core.PAYSTACK_SECRET = "sk_test"
    body = json.dumps({"event": "charge.success", "data": {"reference": "R1", "metadata": {"user_id": 1, "tier": "Founder"}}}).encode()
    sig = hmac.new(b"sk_test", body, hashlib.sha512).hexdigest()
    r = env.client.post("/api/evosgpt/webhook/paystack", content=body, headers={"x-paystack-signature": sig}).json()
    assert r["status"] == "invalid_tier" and env.db.t["users"][0]["evosgpt_tier"] == "Basic"


def test_mount_registers_routes_under_api_evosgpt_and_can_be_disabled(env, monkeypatch):
    from fastapi import FastAPI
    from routes.evosgpt import mount_evosgpt
    app = FastAPI()
    assert mount_evosgpt(app) is True
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/evosgpt/chat" in paths and "/api/evosgpt/currency" in paths and "/api/evosgpt/auth/login" in paths
    assert "/api/evosgpt/webhook/evosgpt-paystack" in paths
    assert not any(p in paths for p in ("/chat", "/auth/login", "/webhook/paystack"))   # nothing leaks to the root
    monkeypatch.setenv("EVOSGPT_ENABLED", "false")
    off = FastAPI()
    assert mount_evosgpt(off) is False and not [r for r in off.routes if "evosgpt" in getattr(r, "path", "")]
