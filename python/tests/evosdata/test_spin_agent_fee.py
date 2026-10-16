"""
Run:  python test_spin_agent_fee.py
Fake-database tests (same approach as test_evoxera_bot.py) for spin.py, agent_fee.py and the
user-token helpers added to main.py. No network, no real Supabase, no real Paystack.
"""
import os, sys, json, types, time
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.getcwd())
for k in ["SUPABASE_URL","SUPABASE_KEY","PAYSTACK_SECRET_KEY","DATAMART_API_KEY","DATAMART_WEBHOOK_SECRET",
          "BUNDLES_GHANA_API_KEY","BUNDLES_GHANA_API_SECRET","MOOLRE_USERNAME","MOOLRE_API_KEY","MOOLRE_ACCOUNT_NUMBER",
          "SWIFT_DATA_LINK_API_KEY","AGYEKUMDATA_API_KEY","AGYEKUMDATA_WEBHOOK_SECRET","ADMIN_SECRET","SMTP_PASSWORD"]:
    os.environ[k] = "x"

UNIQUE = {"spins": [("user_id", "spin_date")], "spin_boost_orders": [("order_id",)],
          "agent_fee_payments": [("reference",)]}
def iso(dt): return dt.isoformat()
def now(): return datetime.now(timezone.utc)

DB = {t: [] for t in ["users", "orders", "prices", "spins", "spin_boost_orders", "agent_fee_payments",
                      "provider_routes", "wa_sessions", "wa_alerts"]}
DB["prices"] = [{"network": "MTN", "bundle": f"{g}GB", "price": 4.5 * g} for g in range(1, 11)] \
             + [{"network": "AIRTELTIGO", "bundle": f"{g}GB", "price": 4 * g} for g in range(1, 11) if g != 7] \
             + [{"network": "TELECEL", "bundle": "10GB", "price": 40}, {"network": "TELECEL", "bundle": "5GB", "price": 20}]
DB["provider_routes"] = [{"network": n, "provider": "DATAMART", "priority": 1, "active": True}
                         for n in ("MTN", "AIRTELTIGO", "TELECEL")]

class Q:
    def __init__(s, t): s.t = t; s.f = []; s.op = "select"; s.payload = None; s.lim = None; s.ord = None
    def select(s, *a, **k): return s
    def eq(s, c, v): s.f.append(lambda r: r.get(c) == v); return s
    def neq(s, c, v): s.f.append(lambda r: r.get(c) != v); return s
    def in_(s, c, vs): s.f.append(lambda r: r.get(c) in vs); return s
    def gte(s, c, v): s.f.append(lambda r: str(r.get(c) or "") >= str(v)); return s
    def lte(s, c, v): s.f.append(lambda r: str(r.get(c) or "") <= str(v)); return s
    def or_(s, expr):   # only the login lookup: "username.eq.X,email.eq.X"
        vals = [p.split(".eq.", 1) for p in expr.split(",")]
        s.f.append(lambda r: any(r.get(k) == v for k, v in vals)); return s
    def order(s, c, desc=False): s.ord = (c, desc); return s
    def limit(s, n): s.lim = n; return s
    def single(s): s.lim = 1; return s
    def insert(s, p): s.op = "insert"; s.payload = p; return s
    def update(s, p): s.op = "update"; s.payload = p; return s
    def delete(s): s.op = "delete"; return s
    def execute(s):
        rows = DB.setdefault(s.t, [])
        if s.op == "insert":
            p = dict(s.payload)
            for cols in UNIQUE.get(s.t, []):
                if any(all(r.get(c) == p.get(c) for c in cols) for r in rows):
                    raise Exception(f"duplicate key value violates unique constraint on {s.t}{cols}")
            p.setdefault("id", len(rows) + 1)
            p.setdefault("created_at", iso(now()))
            rows.append(p)
            return types.SimpleNamespace(data=[dict(p)])
        m = [r for r in rows if all(f(r) for f in s.f)]
        if s.op == "update":
            for r in m: r.update(s.payload)
            return types.SimpleNamespace(data=[dict(r) for r in m])
        if s.op == "delete":
            for r in m: rows.remove(r)
            return types.SimpleNamespace(data=m)
        if s.ord: m.sort(key=lambda r: str(r.get(s.ord[0]) or ""), reverse=s.ord[1])
        if s.lim: m = m[:s.lim]
        return types.SimpleNamespace(data=[dict(r) for r in m])
class FakeSB:
    def table(s, t): return Q(t)
import supabase
supabase.create_client = lambda *a, **k: FakeSB()

# ---------- fake outbound http ----------
import requests
class R:
    def __init__(s, j): s._j = j; s.status_code = 200; s.text = json.dumps(j)
    def json(s): return s._j
HTTP = []
PAYSTACK_VERIFY = {}          # reference -> data dict returned by /transaction/verify
DATAMART_OK = [True]
def fake_post(url, **kw):
    HTTP.append(("POST", url, kw.get("json")))
    if "paystack.co/transaction/initialize" in url:
        return R({"status": True, "data": {"reference": kw["json"]["reference"], "authorization_url": "https://checkout.paystack.com/x"}})
    if "datamartgh" in url and url.endswith("/purchase"):
        return R({"data": {"orderReference": "DM-REF-1", "orderId": "DM-1"}} if DATAMART_OK[0] else {"error": "no wallet"})
    raise AssertionError("unexpected POST " + url)
def fake_get(url, **kw):
    HTTP.append(("GET", url, None))
    if "transaction/verify/" in url:
        ref = url.rsplit("/", 1)[1]
        d = PAYSTACK_VERIFY.get(ref)
        return R({"status": True, "data": d} if d else {"status": False, "message": "Transaction reference not found"})
    raise AssertionError("unexpected GET " + url)
requests.post = fake_post
requests.get = fake_get

from services.evosdata import core as main, spin, agent_fee
from fastapi import FastAPI
from routes.evosdata import mount_evosdata
_app = FastAPI()
mount_evosdata(_app, prefix="")   # root paths, as the standalone app had them
from fastapi.testclient import TestClient
assert spin._installed and agent_fee._installed, "modules failed to mount"
c = TestClient(_app)

def H(uid): return {"X-User-Token": main.make_user_token(uid)}
def new_user(uid, **kw):
    DB["users"].append({"id": uid, "email": f"u{uid}@x.com", "username": f"u{uid}", "role": "user", "agent_status": "pending", **kw})
passed = [0]
def ok(cond, msg):
    assert cond, "FAIL: " + msg
    passed[0] += 1
    print("  ok -", msg)

# =====================================================================
print("USER TOKENS")
t = main.make_user_token(7)
ok(main.verify_user_token(t, 7), "valid token verifies")
ok(not main.verify_user_token(t, 8), "token for user 7 rejected for user 8")
ok(not main.verify_user_token(main.make_user_token(7, ttl=-5), 7), "expired token rejected")
ok(not main.verify_user_token(main.make_agent_token(7), 7), "AGENT token is not accepted as a user token")
ok(not main.verify_agent_token(t, 7), "USER token is not accepted as an agent token (cannot reach /agent/* routes)")
ok(not main.verify_user_token("garbage", 7), "garbage rejected")

print("LOGIN issues a user_token")
new_user(1, password=main.pwd_context.hash("secret123"), username="kofi", full_name="Kofi", referral_code="k", rank=1)
r = c.post("/auth/login", json={"username": "kofi", "password": "secret123"}).json()
ok(r["status"] == "ok" and main.verify_user_token(r["user"]["user_token"], 1), "login returns a valid user_token")
ok(r["user"]["agent_token"] is None, "plain customer still gets no agent token")

# =====================================================================
print("ODDS")
import random
random.seed(1)
N = 400000
def sim(boosted):
    cnt = {}
    for _ in range(N):
        p = spin.pick_prize(boosted, 1e9)
        cnt[p] = cnt.get(p, 0) + 1
    return {k: v / N * 100 for k, v in cnt.items()}
spin._rng = random.Random(42)
n = sim(False); b = sim(True)
print("   normal :", {k: round(v, 2) for k, v in sorted(n.items(), key=lambda x: (x[0] is None, x[0]))})
print("   boosted:", {k: round(v, 2) for k, v in sorted(b.items(), key=lambda x: (x[0] is None, x[0]))})
ok(0.85 < n[1] < 1.15, f"normal 1GB ~1% (got {n[1]:.2f}%)")
ok(0.03 < n[10] < 0.07, f"10GB ~0.05% = about 1 in 2000 (got {n[10]:.3f}%)")
ok(24 < b[1] < 26, f"boosted 1GB ~25% (got {b[1]:.2f}%)")
ok(abs(b[10] - n[10]) < 0.04, "boost does not change the 10GB odds")
ok(spin.pick_prize(True, 0.0, roll=10) is None, "daily cap reached -> Try again even on a winning roll")
ok(spin.pick_prize(True, 0.5, roll=10) is None and spin.pick_prize(True, 1, roll=10) == 1, "cap compares prize size to GB left")
ok(len(spin.SEGMENTS) == 20 and spin.SEGMENTS[:4] == [1, None, 2, None] and spin.SEGMENTS[-2:] == [10, None], "wheel is 1GB, Try again, 2GB, Try again ... 10GB, Try again")
ok(all(spin.SEGMENTS[spin.segment_for(g)] == g for g in range(1, 11)) and spin.SEGMENTS[spin.segment_for(None)] is None, "segment_for lands on the right slice")
spin._rng = random.SystemRandom()

# =====================================================================
print("SPIN: auth and one-per-day")
r = c.post("/spin", json={"user_id": 1})
ok(r.status_code == 403, "no token -> 403")
r = c.post("/spin", json={"user_id": 1}, headers=H(2))
ok(r.status_code == 403, "someone else's token -> 403")
s = c.get("/spin/status?user_id=1", headers=H(1)).json()
ok(s["can_spin"] and len(s["segments"]) == 20, "status: can spin, 20 segments")
real_pick = spin.pick_prize
spin.pick_prize = lambda boosted, left, roll=None: None
r = c.post("/spin", json={"user_id": 1}, headers=H(1)).json()
ok(r["status"] == "ok" and not r["won"] and r["prize_gb"] is None and spin.SEGMENTS[r["segment_index"]] is None, "first spin works (Try again)")
r2 = c.post("/spin", json={"user_id": 1}, headers=H(1)).json()
ok(r2["status"] == "already_spun" and not r2["can_spin"], "second spin the same day refused")
ok(len(DB["spins"]) == 1, "only one spins row for the day")
# next day resets
DB["spins"][0]["spin_date"] = (now().date() - timedelta(days=1)).isoformat()
ok(c.get("/spin/status?user_id=1", headers=H(1)).json()["can_spin"], "next UTC day: spin is available again")

# =====================================================================
print("SPIN: hidden 3GB+ boost, each purchase counts once")
new_user(2)
seen = []
spin.pick_prize = lambda boosted, left, roll=None: (seen.append(boosted), None)[1]
DB["orders"] += [
    {"id": 101, "user_id": 2, "bundle": "2GB", "status": "successful", "source": None, "created_at": iso(now())},
    {"id": 102, "user_id": 2, "bundle": "5GB", "status": "pending_payment", "source": None, "created_at": iso(now())},
    {"id": 103, "user_id": 2, "bundle": "10GB", "status": "successful", "source": "spin", "created_at": iso(now())},
    {"id": 104, "user_id": 2, "bundle": "3GB", "status": "successful", "source": None, "created_at": iso(now() - timedelta(hours=60))},
]
c.post("/spin", json={"user_id": 2}, headers=H(2))
ok(seen[-1] is False, "2GB / unpaid / spin-reward / too-old orders do NOT boost")
DB["spins"][-1]["spin_date"] = "2000-01-01"
DB["orders"].append({"id": 105, "user_id": 2, "bundle": "3GB", "status": "successful", "source": None, "created_at": iso(now())})
c.post("/spin", json={"user_id": 2}, headers=H(2))
ok(seen[-1] is True and DB["spin_boost_orders"][-1]["order_id"] == 105, "a paid 3GB order boosts the spin and is recorded")
DB["spins"][-1]["spin_date"] = "2000-01-02"
c.post("/spin", json={"user_id": 2}, headers=H(2))
ok(seen[-1] is False, "the same purchase does not boost a second spin")
spin.pick_prize = real_pick

# =====================================================================
print("SPIN: daily cap")
new_user(3); new_user(4)
spin.DAILY_CAP_GB = 5
DB["spins"].append({"id": 900, "user_id": 99, "spin_date": spin._today(), "prize_gb": 4, "status": "won", "created_at": iso(now())})
spin.pick_prize = lambda boosted, left, roll=None: real_pick(boosted, left, roll=0.0)   # always a winning roll (1GB)
r = c.post("/spin", json={"user_id": 3}, headers=H(3)).json()
ok(r["won"] and r["prize_gb"] == 1, "1GB still fits under the 5GB cap (4 given + 1)")
r = c.post("/spin", json={"user_id": 4}, headers=H(4)).json()
ok(not r["won"], "next winning roll is refused because the daily cap is reached")
spin.DAILY_CAP_GB = 50
DB["spins"] = [x for x in DB["spins"] if x["id"] != 900]

# =====================================================================
print("CLAIM: network rules, atomic, dispatch")
def win(uid, gb):
    spin.pick_prize = lambda boosted, left, roll=None: gb
    DB["spins"] = [x for x in DB["spins"] if not (x["user_id"] == uid and x["spin_date"] == spin._today())]
    return c.post("/spin", json={"user_id": uid}, headers=H(uid)).json()

new_user(5)
w = win(5, 5)
ok(w["won"] and w["networks"]["TELECEL"]["available"] is False and w["networks"]["MTN"]["available"] and w["networks"]["AIRTELTIGO"]["available"],
   "5GB prize: Telecel greyed out, MTN + AirtelTigo open")
st = c.get("/spin/status?user_id=5", headers=H(5)).json()
ok(st["pending_prize"]["spin_id"] == w["spin_id"] and st["pending_prize"]["prize_gb"] == 5, "unclaimed win is remembered (popup can reopen)")
body = lambda net, phone="0241234567", sid=None, uid=5: {"user_id": uid, "spin_id": sid or w["spin_id"], "phone": phone, "network": net}
r = c.post("/spin/claim", json=body("TELECEL"), headers=H(5))
ok(r.status_code == 400 and "10GB" in r.text, "server refuses Telecel for a 5GB prize")
r = c.post("/spin/claim", json=body("Vodafone"), headers=H(5))
ok(r.status_code == 400, "'Vodafone' is treated as Telecel and refused too")
r = c.post("/spin/claim", json=body("MTN", phone="abc"), headers=H(5))
ok(r.status_code == 400, "bad phone number refused")
r = c.post("/spin/claim", json=body("MTN"), headers=H(6) if False else {"X-User-Token": main.make_user_token(6)})
ok(r.status_code == 403, "claim with someone else's token refused")
ok(DB["spins"][-1]["status"] == "won", "failed attempts did not consume the prize")

HTTP.clear()
r = c.post("/spin/claim", json=body("MTN"), headers=H(5)); j = r.json()
ok(r.status_code == 200 and j["status"] == "claimed" and j["delivery"] == "sent", "MTN claim succeeds and dispatches immediately")
o = DB["orders"][-1]
ok(o["source"] == "spin" and o["price"] == 0 and o["bundle"] == "5GB" and o["network"] == "MTN" and o["phone_number"] == "0241234567"
   and o["status"] == "processing" and o["datamart_ref"] == "DM-REF-1" and o["paystack_ref"].startswith("EVOS-SPIN-"),
   "reward order is a normal processing order tagged source=spin, price 0")
dm = [h for h in HTTP if "datamartgh" in h[1]][0][2]
ok(dm == {"phoneNumber": "0241234567", "network": "YELLO", "capacity": "5", "gateway": "wallet"}, "same DataMart payload as a paid order")
r = c.post("/spin/claim", json=body("MTN"), headers=H(5))
ok(r.status_code == 409, "claiming twice is refused (409)")
ok(sum(1 for x in DB["orders"] if x.get("source") == "spin" and x["user_id"] == 5) == 1, "still only one reward order")
ok(c.get("/spin/status?user_id=5", headers=H(5)).json()["pending_prize"] is None, "claimed prize no longer pending")

new_user(6)
w = win(6, 10)
ok(all(v["available"] for v in w["networks"].values()), "10GB prize: Telecel/Vodafone becomes active")
r = c.post("/spin/claim", json=body("TELECEL", sid=w["spin_id"], uid=6), headers=H(6)); j = r.json()
ok(r.status_code == 200 and DB["orders"][-1]["network"] == "TELECEL" and DB["orders"][-1]["bundle"] == "10GB", "10GB on Telecel claims fine")

new_user(7)
w = win(7, 7)
ok(w["networks"]["AIRTELTIGO"] == {"available": False, "reason": "7GB not available"}, "a network that does not sell that size is greyed out")
r = c.post("/spin/claim", json=body("AIRTELTIGO", sid=w["spin_id"], uid=7), headers=H(7))
ok(r.status_code == 400 and DB["spins"][-1]["status"] == "won", "claim on it refused, prize kept")

new_user(8)
w = win(8, 3)
DATAMART_OK[0] = False
r = c.post("/spin/claim", json=body("MTN", sid=w["spin_id"], uid=8), headers=H(8)); j = r.json()
o = DB["orders"][-1]
ok(r.status_code == 200 and j["delivery"] == "queued" and o["status"] == "processing" and not o.get("datamart_ref"),
   "provider failure: user still sees success, order left processing with no ref for retry_stuck_orders()")
DATAMART_OK[0] = True

new_user(9)
w = win(9, 2)
DB["spins"][-1]["created_at"] = iso(now() - timedelta(days=8))
r = c.post("/spin/claim", json=body("MTN", sid=w["spin_id"], uid=9), headers=H(9))
ok(r.status_code == 410 and DB["spins"][-1]["status"] == "expired", "win older than 7 days has expired")
spin.pick_prize = real_pick

# =====================================================================
print("AGENT FEE")
new_user(20); new_user(21, role="admin")
r = c.post("/agent-fee/initiate", json={"user_id": 20})
ok(r.status_code == 403, "initiate needs a token")
HTTP.clear()
r = c.post("/agent-fee/initiate", json={"user_id": 20, "amount": 1}, headers=H(20)); j = r.json()
init = [h for h in HTTP if "initialize" in h[1]][0][2]
ok(j["status"] == "created" and init["amount"] == 5000 and init["currency"] == "GHS", "Paystack charged GH₵50.00 (5000 pesewas); a browser-sent amount is ignored")
ref = j["reference"]
ok(init["callback_url"].endswith(f"/success?type=agent-fee&reference={ref}"), "callback returns to the success page")
ok(c.post("/agent-fee/initiate", json={"user_id": 21}, headers=H(21)).status_code == 400, "admin cannot buy agent status")
st = c.get(f"/agent-fee/status?user_id=20&reference={ref}", headers=H(20)).json()
ok(st["state"] == "pending", "unpaid attempt stays pending")

PAYSTACK_VERIFY[ref] = {"status": "success", "amount": 5000, "paid_at": iso(now() - timedelta(minutes=2))}
st = c.get(f"/agent-fee/status?user_id=20&reference={ref}", headers=H(20)).json()
ok(st["state"] == "paid" and st["activate_after"], "payment seen -> 'paid', waiting")
agent_fee.run_once()
u = [x for x in DB["users"] if x["id"] == 20][0]
ok(u["role"] == "user", "2 minutes after payment: NOT an agent yet (30-minute wait)")
ok(c.post("/agent-fee/initiate", json={"user_id": 20}, headers=H(20)).json()["status"] == "waiting", "cannot pay twice while waiting")

row = [x for x in DB["agent_fee_payments"] if x["reference"] == ref][0]
row["paid_at"] = iso(now() - timedelta(minutes=31)); row["activate_after"] = iso(now() - timedelta(minutes=1))
HTTP.clear()
agent_fee.run_once()
ok(any("transaction/verify" in h[1] for h in HTTP), "verifies with Paystack again at activation time")
ok(u["role"] == "agent" and u["agent_status"] == "approved" and row["status"] == "activated", "30 minutes later: verified and upgraded to agent automatically")
agent_fee.run_once(); agent_fee.run_once()
ok(row["status"] == "activated", "running the job again changes nothing")
ok(c.post("/agent-fee/initiate", json={"user_id": 20}, headers=H(20)).json()["status"] == "already_agent", "an agent cannot pay again")
sj = c.get("/agent-fee/status?user_id=20", headers=H(20)).json()
ok(sj["is_agent"] and main.verify_agent_token(sj["agent_token"], 20), "status reports is_agent and hands over a working agent token (no re-login needed)")
ok("agent_token" not in c.get("/agent-fee/status?user_id=1", headers=H(1)).json(), "non-agents never receive an agent token")

# customer closed the page: the job alone finds the payment
new_user(22)
HTTP.clear()
j = c.post("/agent-fee/initiate", json={"user_id": 22}, headers=H(22)).json(); ref2 = j["reference"]
PAYSTACK_VERIFY[ref2] = {"status": "success", "amount": 5000, "paid_at": iso(now() - timedelta(minutes=45))}
agent_fee.run_once()
ok([x for x in DB["users"] if x["id"] == 22][0]["role"] == "agent", "paid and left the page: background job still activates after 30 min")

# underpaid / abandoned / failed
new_user(23)
j = c.post("/agent-fee/initiate", json={"user_id": 23}, headers=H(23)).json(); ref3 = j["reference"]
PAYSTACK_VERIFY[ref3] = {"status": "success", "amount": 100, "paid_at": iso(now() - timedelta(minutes=45))}
agent_fee.run_once()
ok([x for x in DB["users"] if x["id"] == 23][0]["role"] == "user" and [x for x in DB["agent_fee_payments"] if x["reference"] == ref3][0]["status"] == "failed",
   "underpaid transaction is never activated")
new_user(24)
j = c.post("/agent-fee/initiate", json={"user_id": 24}, headers=H(24)).json(); ref4 = j["reference"]
PAYSTACK_VERIFY[ref4] = {"status": "abandoned", "amount": 5000}
r4 = [x for x in DB["agent_fee_payments"] if x["reference"] == ref4][0]
agent_fee.run_once()
ok(r4["status"] == "pending", "abandoned (not yet paid) keeps waiting")
r4["created_at"] = iso(now() - timedelta(hours=25)); r4["last_checked_at"] = iso(now() - timedelta(minutes=10))
agent_fee.run_once()
ok(r4["status"] == "expired", "never paid for 24h -> expired")

print(f"\nALL {passed[0]} CHECKS PASSED")
