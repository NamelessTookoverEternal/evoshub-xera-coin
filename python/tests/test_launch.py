"""
Official-launch backend tests (HTTP + service layer).

The database rules themselves (tier boundaries, atomicity, bonus slots,
concurrency, reconciliation) are proven against real Postgres by
supabase/tests/run_launch_tests.sh and run_launch_concurrency_test.sh. These
tests prove the PYTHON layer around them: that identity comes from the token,
that acceptance needs the exact version + hash + checkbox, that every database
refusal is reported as a failure (never as an active miner), that nothing in
Python can pick a reward or a user, and that the shared login behaves.
"""

import os
import re
import sys
import time
import types
from pathlib import Path

import pytest

os.environ.setdefault("XERA_TOKEN_SECRET", "test-secret-test-secret-test-secret")
os.environ.setdefault("SUPABASE_URL", "https://abc.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZSJ9.abc")

# routes_auth pulls in a module that connects to Supabase at import time.
if "utils.xera_supabase" not in sys.modules:
    _stub = types.ModuleType("utils.xera_supabase")
    _stub.supabase = types.SimpleNamespace()
    sys.modules["utils.xera_supabase"] = _stub

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from utils.rate_limit import limiter
from xera import agreement, daily, launch, mining, routes, routes_auth, user_auth

REPO = Path(__file__).resolve().parents[2]
ROOT_PY = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Fake Supabase: tables for the config reads, programmable RPCs
# --------------------------------------------------------------------------
class _Res:
    def __init__(self, data):
        self.data = data
        self.count = len(data) if isinstance(data, list) else None

    def execute(self):
        return self


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a):
        return self

    def limit(self, *a):
        return self

    def execute(self):
        return _Res(list(self.rows))


class FakeDB:
    def __init__(self):
        self.tables = {
            "xera_config": [{"id": 1, "system_enabled": True, "mining_enabled": True,
                             "sale_enabled": False, "withdrawal_enabled": False,
                             "transfer_enabled": False, "current_phase": "mining"}],
            "xera_mining_config": [{"id": 1, "session_hours": 24, "max_reward_per_session": 5000,
                                    "min_reward_per_session": 1, "mining_end": None}],
            "xera_allocations": [{"id": 1, "total_target": 500000000, "mining_allocation": 75000000,
                                  "mining_distributed": 0}],
            "xera_daily_config": [{"id": 1, "enabled": True, "reward_amount": 2}],
            "xera_daily_claims": [],
            "xera_wallets": [{"id": 1, "user_id": 5, "cached_balance": 0, "status": "ACTIVE"}],
            "xera_mining_sessions": [],
            "xera_security_events": [],
        }
        self.handlers = {}
        self.calls = []
        self.launch_cfg = {
            "active_miners": 0, "next_miner_position": 1, "base_reward_estimate": 10,
            "bonus_enabled": True, "bonus_amount": 100, "bonus_total_slots": 100,
            "bonus_slots_remaining": 100,
            "agreement_version": agreement.AGREEMENT_VERSION,
            "welcome_notice_version": "xera-official-launch-2026-10-v1",
        }

    def table(self, name):
        if name == "xera_security_events":
            return _SecEvents(self)
        return _Table(self.tables.get(name, []))

    def rpc(self, name, params=None):
        self.calls.append((name, dict(params or {})))
        if name not in self.handlers:
            raise RuntimeError(f"unstubbed rpc {name}")
        out = self.handlers[name](params or {})
        return out if hasattr(out, "execute") else _Res(out)

    def calls_to(self, name):
        return [p for n, p in self.calls if n == name]


class _SecEvents:
    def __init__(self, db):
        self.db = db

    def insert(self, row):
        self.db.tables["xera_security_events"].append(row)
        return _Res([row])


def _install(db):
    for mod in (routes, launch, mining, daily):
        mod.supabase = db
    import xera.config as cfg
    import xera.wallet as wallet
    cfg.supabase = db
    wallet.supabase = db


@pytest.fixture
def db():
    d = FakeDB()

    def status(p):
        out = dict(d.launch_cfg)
        if p.get("p_user_id") is not None:
            out.update(agreement_accepted=False, bonus_received=False, welcome_seen=False)
        return out

    d.handlers["xera_launch_status"] = status
    _install(d)
    return d


@pytest.fixture
def client(db):
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(routes.router, prefix="/api/xera")
    app.include_router(routes_auth.router, prefix="/api/xera/auth")
    limiter.reset()
    return TestClient(app, raise_server_exceptions=False)


def auth(uid):
    return {"Authorization": f"Bearer {user_auth.make_user_token(uid)}"}


def pg_error(msg, code="P0001"):
    return Exception(f"{{'code': '{code}', 'details': None, 'hint': None, 'message': '{msg}'}}")


def ok_session(**over):
    out = {
        "session_id": 77, "user_id": 5, "started_at": "2026-10-21T10:00:00Z",
        "expires_at": "2026-10-22T10:00:00Z", "status": "ACTIVE", "rate_snapshot": 10,
        "estimated_reward": 10, "active_miners": 1, "bonus_status": "GRANTED",
        "bonus_amount": 100, "bonus_slot": 1, "new_balance": 100,
    }
    out.update(over)
    return out


# --------------------------------------------------------------------------
# Agreement text
# --------------------------------------------------------------------------
def test_agreement_has_all_sixteen_sections_in_order():
    titles = [s["title"] for s in agreement.SECTIONS]
    assert len(titles) == 16
    assert [int(t.split(".")[0]) for t in titles] == list(range(1, 17))


def test_agreement_hash_is_sha256_of_the_published_text():
    import hashlib
    assert agreement.AGREEMENT_SHA256 == hashlib.sha256(agreement.agreement_text().encode()).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", agreement.AGREEMENT_SHA256)
    assert agreement.AGREEMENT_VERSION in agreement.agreement_text()


def test_agreement_makes_no_forbidden_promises():
    text = agreement.agreement_text()
    for phrase in (
        "Scrolling alone is not acceptance",
        "not a token on a blockchain",
        "On-chain claiming has not launched",
        "does not by itself make you eligible",
        "We make no promise of profit",
        "Nothing here limits any rights you have under applicable law",
    ):
        assert phrase in text
    assert "waive" not in text.lower()


def test_agreement_reward_tiers_match_the_database_function():
    sql = (REPO / "supabase/migrations/20261021_xera_official_launch_v1.sql").read_text()
    body = sql[sql.index("xera_base_reward_for_active_miners(p_active_miners"):]
    body = body[: body.index("$$;", body.index("SELECT CASE"))]
    sql_tiers = [(int(a), b) for a, b in re.findall(r"<= (\d+)\s+THEN ([0-9.]+)::NUMERIC", body)]
    sql_else = re.search(r"ELSE ([0-9.]+)::NUMERIC", body).group(1)
    py = [(hi, rw) for hi, rw in agreement.REWARD_TIERS if hi is not None]
    assert [(h, str(float(r)).rstrip("0").rstrip(".")) for h, r in sql_tiers] == \
           [(h, str(float(r)).rstrip("0").rstrip(".")) for h, r in py]
    assert float(sql_else) == float(agreement.REWARD_TIERS[-1][1]) == 1.0


def test_agreement_endpoint_is_public_and_matches_module(client):
    r = client.get("/api/xera/launch/agreement")
    assert r.status_code == 200
    doc = r.json()["agreement"]
    assert doc["version"] == agreement.AGREEMENT_VERSION
    assert doc["sha256"] == agreement.AGREEMENT_SHA256
    assert len(doc["sections"]) == 16


# --------------------------------------------------------------------------
# Agreement acceptance
# --------------------------------------------------------------------------
def accept_body(**over):
    body = {"agreement_version": agreement.AGREEMENT_VERSION,
            "content_sha256": agreement.AGREEMENT_SHA256, "confirmed": True}
    body.update(over)
    return body


def test_accept_requires_a_valid_token(client, db):
    assert client.post("/api/xera/launch/agreement/accept", json=accept_body()).status_code == 401
    r = client.post("/api/xera/launch/agreement/accept", json=accept_body(),
                    headers={"Authorization": "Bearer garbage.token"})
    assert r.status_code == 401
    assert db.calls_to("xera_accept_miner_agreement") == []


def test_accept_needs_the_checkbox(client, db):
    r = client.post("/api/xera/launch/agreement/accept", json=accept_body(confirmed=False), headers=auth(5))
    assert r.status_code == 400
    assert db.calls_to("xera_accept_miner_agreement") == []
    r = client.post("/api/xera/launch/agreement/accept",
                    json={k: v for k, v in accept_body().items() if k != "confirmed"}, headers=auth(5))
    assert r.status_code == 422
    assert db.calls_to("xera_accept_miner_agreement") == []


def test_accept_rejects_wrong_version_and_wrong_hash(client, db):
    r = client.post("/api/xera/launch/agreement/accept",
                    json=accept_body(agreement_version="old-version"), headers=auth(5))
    assert r.status_code == 409
    r = client.post("/api/xera/launch/agreement/accept",
                    json=accept_body(content_sha256="0" * 64), headers=auth(5))
    assert r.status_code == 409
    assert db.calls_to("xera_accept_miner_agreement") == []
    rejected = [e for e in db.tables["xera_security_events"] if e["event_type"] == "AGREEMENT_ACCEPT_REJECTED"]
    assert len(rejected) == 2


def test_accept_records_for_the_token_user_with_server_text_hash(client, db):
    db.handlers["xera_accept_miner_agreement"] = lambda p: {
        "accepted": True, "already_accepted": False,
        "agreement_version": p["p_version"], "accepted_at": "2026-10-21T10:00:00Z"}
    # A body that tries to name another user is ignored: the token decides.
    r = client.post("/api/xera/launch/agreement/accept",
                    json={**accept_body(), "user_id": 999}, headers=auth(5))
    assert r.status_code == 200
    (call,) = db.calls_to("xera_accept_miner_agreement")
    assert call["p_user_id"] == 5
    assert call["p_version"] == agreement.AGREEMENT_VERSION
    assert call["p_content_hash"] == agreement.AGREEMENT_SHA256
    assert r.json()["accepted"] is True and r.json()["already_accepted"] is False


def test_accept_is_idempotent_on_retry(client, db):
    state = {"n": 0}

    def handler(p):
        state["n"] += 1
        return {"accepted": True, "already_accepted": state["n"] > 1,
                "agreement_version": p["p_version"], "accepted_at": "2026-10-21T10:00:00Z"}

    db.handlers["xera_accept_miner_agreement"] = handler
    first = client.post("/api/xera/launch/agreement/accept", json=accept_body(), headers=auth(5)).json()
    second = client.post("/api/xera/launch/agreement/accept", json=accept_body(), headers=auth(5)).json()
    assert first["already_accepted"] is False and second["already_accepted"] is True


def test_accept_refuses_when_database_requires_a_different_version(client, db):
    db.launch_cfg["agreement_version"] = "xera-miner-agreement-2099-v9"
    db.handlers["xera_accept_miner_agreement"] = lambda p: pytest.fail("must not record a hash of the wrong text")
    r = client.post("/api/xera/launch/agreement/accept", json=accept_body(), headers=auth(5))
    assert r.status_code == 503
    assert db.calls_to("xera_accept_miner_agreement") == []


def test_accept_reports_migration_not_applied_as_unavailable(client, db):
    def missing(p):
        raise Exception("{'code': 'PGRST202', 'message': 'Could not find the function public.xera_launch_status'}")
    db.handlers["xera_launch_status"] = missing
    r = client.post("/api/xera/launch/agreement/accept", json=accept_body(), headers=auth(5))
    assert r.status_code == 503


# --------------------------------------------------------------------------
# Mining start
# --------------------------------------------------------------------------
def test_start_requires_a_valid_token(client, db):
    assert client.post("/api/xera/mining/start").status_code == 401
    assert db.calls_to("xera_start_mining_launch") == []


def test_start_without_agreement_is_refused_with_a_code_and_no_session(client, db):
    db.handlers["xera_start_mining_launch"] = lambda p: (_ for _ in ()).throw(pg_error("agreement_required", "P0300"))
    r = client.post("/api/xera/mining/start", headers=auth(5))
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "agreement_required"
    assert "mining" not in body and body.get("status") != "ok"


def test_start_success_returns_session_and_bonus_from_the_database(client, db):
    db.handlers["xera_start_mining_launch"] = lambda p: ok_session()
    r = client.post("/api/xera/mining/start", headers=auth(5))
    assert r.status_code == 200
    m = r.json()["mining"]
    assert r.json()["status"] == "ok"
    assert m["id"] == 77 and m["status"] == "ACTIVE" and m["estimated_reward"] == 10
    assert m["bonus"] == {"status": "GRANTED", "amount": 100, "slot": 1}


def test_start_sends_only_user_hours_and_cap_never_a_rate(client, db):
    db.handlers["xera_start_mining_launch"] = lambda p: ok_session()
    client.post("/api/xera/mining/start", json={"user_id": 999, "rate": 5000, "bonus": True}, headers=auth(5))
    (call,) = db.calls_to("xera_start_mining_launch")
    assert set(call) == {"p_user_id", "p_hours", "p_max_reward"}
    assert call["p_user_id"] == 5
    assert call["p_hours"] == 24


def test_start_does_not_use_the_legacy_rpc_anywhere_in_python():
    offenders = []
    for path in ROOT_PY.rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        if "xera_start_mining_session" in path.read_text():
            offenders.append(str(path.relative_to(ROOT_PY)))
    assert offenders == []


@pytest.mark.parametrize("db_code,http,code", [
    ("active_session_exists", 409, "active_session_exists"),
    ("free_mining_closed", 403, "free_mining_closed"),
    ("allocation_exhausted", 409, "allocation_exhausted"),
    ("wallet_not_active", 403, "wallet_not_active"),
])
def test_start_database_refusals_are_failures(client, db, db_code, http, code):
    db.handlers["xera_start_mining_launch"] = lambda p: (_ for _ in ()).throw(pg_error(db_code))
    r = client.post("/api/xera/mining/start", headers=auth(5))
    assert r.status_code == http
    assert r.json()["code"] == code
    assert "mining" not in r.json()


def test_start_when_migration_missing_is_503_not_success(client, db):
    def missing(p):
        raise Exception("{'code': 'PGRST202', 'message': 'Could not find the function public.xera_start_mining_launch'}")
    db.handlers["xera_start_mining_launch"] = missing
    r = client.post("/api/xera/mining/start", headers=auth(5))
    assert r.status_code == 503 and r.json()["code"] == "launch_not_ready"


def test_start_unexpected_database_error_is_a_server_error_not_success(client, db):
    db.handlers["xera_start_mining_launch"] = lambda p: (_ for _ in ()).throw(Exception("connection reset"))
    r = client.post("/api/xera/mining/start", headers=auth(5))
    assert r.status_code == 500
    assert '"ok"' not in r.text and "mining" not in r.text


def test_start_without_a_confirmed_session_is_never_reported_as_active(client, db):
    for empty in (None, {}, [], {"session_id": None}):
        db.handlers["xera_start_mining_launch"] = lambda p, e=empty: e
        r = client.post("/api/xera/mining/start", headers=auth(5))
        assert r.status_code == 500 and '"ok"' not in r.text and "mining" not in r.text


def test_start_when_mining_disabled_never_reaches_the_database(client, db):
    db.tables["xera_config"][0]["mining_enabled"] = False
    db.handlers["xera_start_mining_launch"] = lambda p: pytest.fail("must not be called")
    r = client.post("/api/xera/mining/start", headers=auth(5))
    assert r.status_code == 403 and r.json()["code"] == "mining_disabled"


def test_start_retry_of_an_existing_session_reports_a_conflict_not_a_new_bonus(client, db):
    seen = {"n": 0}

    def handler(p):
        seen["n"] += 1
        if seen["n"] == 1:
            return ok_session()
        raise pg_error("active_session_exists", "P0002")

    db.handlers["xera_start_mining_launch"] = handler
    assert client.post("/api/xera/mining/start", headers=auth(5)).status_code == 200
    second = client.post("/api/xera/mining/start", headers=auth(5))
    assert second.status_code == 409 and "bonus" not in second.json()


# --------------------------------------------------------------------------
# Launch status, welcome notice, user isolation
# --------------------------------------------------------------------------
def test_public_launch_has_only_aggregate_fields(client):
    r = client.get("/api/xera/public/launch")
    assert r.status_code == 200
    keys = set(r.json()["launch"])
    assert {"bonus_slots_remaining", "bonus_total_slots", "bonus_amount", "base_reward_estimate"} <= keys
    assert not keys & {"agreement_accepted", "bonus_received", "welcome_seen", "user_id"}


def test_launch_status_is_scoped_to_the_token_user(client, db):
    flags = {5: dict(agreement_accepted=True, bonus_received=True, welcome_seen=True),
             6: dict(agreement_accepted=False, bonus_received=False, welcome_seen=False)}

    def status(p):
        out = dict(db.launch_cfg)
        if p.get("p_user_id") is not None:
            out.update(flags[p["p_user_id"]])
        return out

    db.handlers["xera_launch_status"] = status
    a = client.get("/api/xera/launch/status", headers=auth(5)).json()["launch"]
    b = client.get("/api/xera/launch/status", headers=auth(6)).json()["launch"]
    assert a["agreement_accepted"] and a["bonus_received"] and a["welcome_seen"]
    assert not (b["agreement_accepted"] or b["bonus_received"] or b["welcome_seen"])
    assert a["agreement_consistent"] is True
    # There is no way to ask about someone else.
    r = client.get("/api/xera/launch/status?user_id=6", headers=auth(5)).json()["launch"]
    assert r["agreement_accepted"] is True


def test_launch_status_flags_a_version_mismatch(client, db):
    db.launch_cfg["agreement_version"] = "something-else"
    r = client.get("/api/xera/launch/status", headers=auth(5)).json()["launch"]
    assert r["agreement_consistent"] is False


def test_launch_status_requires_token(client):
    assert client.get("/api/xera/launch/status").status_code == 401


def test_welcome_seen_marks_the_token_user_and_checks_version(client, db):
    db.handlers["xera_mark_launch_notice_seen"] = lambda p: True
    r = client.post("/api/xera/launch/welcome/seen",
                    json={"notice_version": "xera-official-launch-2026-10-v1", "user_id": 99}, headers=auth(5))
    assert r.status_code == 200
    assert db.calls_to("xera_mark_launch_notice_seen")[0]["p_user_id"] == 5

    db.handlers["xera_mark_launch_notice_seen"] = lambda p: (_ for _ in ()).throw(pg_error("notice_version_mismatch", "P0304"))
    r = client.post("/api/xera/launch/welcome/seen", json={"notice_version": "old"}, headers=auth(5))
    assert r.status_code == 409
    assert client.post("/api/xera/launch/welcome/seen", json={"notice_version": "x"}).status_code == 401


# --------------------------------------------------------------------------
# Rewards come from the database, not from Python
# --------------------------------------------------------------------------
def test_python_holds_no_reward_table():
    assert not hasattr(mining, "_base_reward_for_active_miners")
    assert not hasattr(mining, "_active_miners_count")


def test_current_rate_uses_the_database_estimate(db):
    db.launch_cfg.update(active_miners=150, base_reward_estimate=8)
    info = mining.current_rate()
    assert info["rate"] == 8.0 and info["active_miners"] == 150


def test_current_rate_is_zero_when_allocation_is_exhausted(db):
    db.tables["xera_allocations"][0]["mining_distributed"] = 75000000
    assert mining.current_rate()["rate"] == 0.0


def test_current_rate_reports_launch_not_ready_when_migration_missing(db):
    def missing(p):
        raise Exception("PGRST202 Could not find the function")
    db.handlers["xera_launch_status"] = missing
    with pytest.raises(mining.MiningError) as e:
        mining.current_rate()
    assert str(e.value) == "launch_not_ready"


def test_public_stats_survives_missing_migration(client, db):
    def missing(p):
        raise Exception("PGRST202 Could not find the function")
    db.handlers["xera_launch_status"] = missing
    r = client.get("/api/xera/public/stats")
    assert r.status_code == 200 and r.json()["active_miners"] == 0


# --------------------------------------------------------------------------
# Daily claim
# --------------------------------------------------------------------------
def test_daily_claim_uses_the_configured_reward(client, db):
    db.handlers["xera_claim_daily_reward"] = lambda p: [{"new_balance": 2, "reward_credited": 2, "streak": 1}]
    r = client.post("/api/xera/daily/claim", headers=auth(5))
    assert r.status_code == 200
    (call,) = db.calls_to("xera_claim_daily_reward")
    assert call == {"p_user_id": 5, "p_reward": 2.0}


def test_daily_reward_follows_config_changes(client, db):
    db.tables["xera_daily_config"][0]["reward_amount"] = 3
    db.handlers["xera_claim_daily_reward"] = lambda p: [{"new_balance": 3, "reward_credited": 3, "streak": 1}]
    client.post("/api/xera/daily/claim", headers=auth(5))
    assert db.calls_to("xera_claim_daily_reward")[0]["p_reward"] == 3.0


def test_daily_duplicate_claim_is_refused(client, db):
    db.handlers["xera_claim_daily_reward"] = lambda p: (_ for _ in ()).throw(pg_error("already_claimed_today"))
    r = client.post("/api/xera/daily/claim", headers=auth(5))
    assert r.status_code == 409
    assert any(e["event_type"] == "DUPLICATE_CLAIM_ATTEMPT" for e in db.tables["xera_security_events"])


def test_daily_status_uses_utc_like_the_database(db):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    db.tables["xera_daily_claims"].append({"user_id": 5, "last_claim_date": today, "streak": 1, "total_claims": 1})
    s = daily.get_daily_status(5)
    assert s["already_claimed_today"] is True and s["can_claim"] is False
    assert s["reward_amount"] == 2.0


# --------------------------------------------------------------------------
# Shared login: token lifetime and refresh
# --------------------------------------------------------------------------
def test_token_default_lifetime_is_seven_days(monkeypatch):
    monkeypatch.delenv("XERA_TOKEN_TTL_SECONDS", raising=False)
    assert user_auth.token_ttl_seconds() == 7 * 24 * 3600
    p = user_auth.verify_user_token_payload(user_auth.make_user_token(5))
    assert abs((p["exp"] - p["ses"]) - 7 * 24 * 3600) <= 2


def test_token_lifetime_is_configurable_but_clamped(monkeypatch):
    monkeypatch.setenv("XERA_TOKEN_TTL_SECONDS", "10")
    assert user_auth.token_ttl_seconds() == 3600
    monkeypatch.setenv("XERA_TOKEN_TTL_SECONDS", str(10 * 365 * 24 * 3600))
    assert user_auth.token_ttl_seconds() == 30 * 24 * 3600
    monkeypatch.setenv("XERA_TOKEN_TTL_SECONDS", "not-a-number")
    assert user_auth.token_ttl_seconds() == 7 * 24 * 3600


def test_existing_token_checks_still_work():
    t = user_auth.make_user_token(9)
    assert user_auth.verify_user_token(t) == 9
    head, _, sig = t.partition(".")
    with pytest.raises(user_auth.XeraTokenInvalid):
        user_auth.verify_user_token(head + "." + sig[:-2] + "AA")
    with pytest.raises(user_auth.XeraTokenInvalid):
        user_auth.verify_user_token("")


def _forge(payload):
    import base64, hashlib, hmac, json
    b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(
        hmac.new(user_auth._secret(), b64.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{b64}.{sig}"


@pytest.fixture
def user_exists(monkeypatch):
    async def lookup(uid):
        return {"id": uid} if uid != 404 else None
    monkeypatch.setattr(routes_auth, "get_public_user_by_id", lookup)


def test_refresh_issues_a_fresh_token_for_the_same_user_and_keeps_sign_in_time(client, user_exists):
    start = int(time.time()) - 3 * 24 * 3600
    old = _forge({"uid": 5, "exp": int(time.time()) + 1000, "ses": start})
    r = client.post("/api/xera/auth/refresh", headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 200
    p = user_auth.verify_user_token_payload(r.json()["token"])
    assert p["uid"] == 5 and p["ses"] == start
    assert p["exp"] > user_auth.verify_user_token_payload(old)["exp"]


def test_refresh_needs_a_valid_token_and_cannot_pick_a_user(client, user_exists):
    assert client.post("/api/xera/auth/refresh").status_code == 401
    assert client.post("/api/xera/auth/refresh", headers={"Authorization": "Bearer x.y"}).status_code == 401
    expired = _forge({"uid": 5, "exp": int(time.time()) - 5, "ses": int(time.time()) - 100})
    assert client.post("/api/xera/auth/refresh", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    r = client.post("/api/xera/auth/refresh?user_id=6", json={"user_id": 6}, headers=auth(5))
    assert user_auth.verify_user_token(r.json()["token"]) == 5


def test_refresh_stops_after_the_absolute_session_limit(client, user_exists):
    too_old = int(time.time()) - user_auth.MAX_SESSION_SECONDS - 60
    t = _forge({"uid": 5, "exp": int(time.time()) + 1000, "ses": too_old})
    assert client.post("/api/xera/auth/refresh", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_refresh_rejects_a_deleted_account(client, user_exists):
    assert client.post("/api/xera/auth/refresh", headers=auth(404)).status_code == 401


def test_refresh_accepts_a_legacy_token_without_a_sign_in_time(client, user_exists):
    legacy = _forge({"uid": 5, "exp": int(time.time()) + 3600})
    r = client.post("/api/xera/auth/refresh", headers={"Authorization": f"Bearer {legacy}"})
    assert r.status_code == 200
    assert user_auth.verify_user_token(r.json()["token"]) == 5
