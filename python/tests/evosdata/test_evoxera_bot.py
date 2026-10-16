import os, sys, json, types, re
sys.path.insert(0, os.getcwd())
for k in ["SUPABASE_URL","SUPABASE_KEY","PAYSTACK_SECRET_KEY","DATAMART_API_KEY","DATAMART_WEBHOOK_SECRET",
          "BUNDLES_GHANA_API_KEY","BUNDLES_GHANA_API_SECRET","MOOLRE_USERNAME","MOOLRE_API_KEY","MOOLRE_ACCOUNT_NUMBER",
          "SWIFT_DATA_LINK_API_KEY","AGYEKUMDATA_API_KEY","AGYEKUMDATA_WEBHOOK_SECRET","ADMIN_SECRET","SMTP_PASSWORD"]:
    os.environ[k] = "x"
os.environ.update(WA_TOKEN="t", WA_PHONE_NUMBER_ID="123", WA_VERIFY_TOKEN="vt", WA_APP_SECRET="appsecret", WA_OWNER_NUMBER="233500000000")

# ---------- fake supabase ----------
DB = {"prices": [
    {"network":"MTN","bundle":f"{g}GB","price":4.5*g} for g in (1,2,3,4,5,6,8,10,15,20,25,30)
] + [{"network":"TELECEL","bundle":"5GB","price":20.0},{"network":"AT","bundle":"2GB","price":9.0}],
 "orders": [], "wa_sessions": [], "wa_alerts": [], "provider_routes":[]}
class Q:
    def __init__(s,t): s.t=t; s.f=[]; s.op="select"; s.payload=None; s.lim=None; s.ord=None
    def select(s,*a,**k): return s
    def eq(s,c,v): s.f.append(lambda r:r.get(c)==v); return s
    def neq(s,c,v): s.f.append(lambda r:r.get(c)!=v); return s
    def in_(s,c,vs): s.f.append(lambda r:r.get(c) in vs); return s
    def gte(s,c,v): return s
    def or_(s,expr): s.f.append(lambda r: r.get("wa_notify")!="done"); return s
    def order(s,c,desc=False): s.ord=(c,desc); return s
    def limit(s,n): s.lim=n; return s
    def insert(s,p): s.op="insert"; s.payload=p; return s
    def update(s,p): s.op="update"; s.payload=p; return s
    def upsert(s,p): s.op="upsert"; s.payload=p; return s
    def execute(s):
        rows=DB.setdefault(s.t,[])
        if s.op=="insert":
            p=dict(s.payload); p.setdefault("id",len(rows)+1); p.setdefault("created_at","2026-10-12T10:00:00+00:00"); rows.append(p); return types.SimpleNamespace(data=[p])
        if s.op=="upsert":
            key="wa_number" if "wa_number" in s.payload else "msg_id"
            for r in rows:
                if r[key]==s.payload[key]: r.update(s.payload); return types.SimpleNamespace(data=[r])
            rows.append(dict(s.payload)); return types.SimpleNamespace(data=[s.payload])
        m=[r for r in rows if all(f(r) for f in s.f)]
        if s.op=="update":
            for r in m: r.update(s.payload)
            return types.SimpleNamespace(data=m)
        if s.ord: m.sort(key=lambda r:r.get(s.ord[0]) or "", reverse=s.ord[1])
        if s.lim: m=m[:s.lim]
        return types.SimpleNamespace(data=m)
class FakeSB:
    def table(s,t): return Q(t)
import supabase
supabase.create_client = lambda *a,**k: FakeSB()

# ---------- mock outbound http ----------
SENT=[]; PAYSTACK=[]; IDS=[0]
import requests
class R:
    def __init__(s,j,code=200): s._j=j; s.status_code=code; s.text=json.dumps(j)
    def json(s): return s._j
real_post = requests.post
def fake_post(url, **kw):
    if "graph.facebook.com" in url:
        SENT.append(kw["json"]); IDS[0]+=1; SENT[-1]["_id"]=f"wamid.{IDS[0]}"; return R({"messages":[{"id":f"wamid.{IDS[0]}"}]})
    if "paystack.co/transaction/initialize" in url:
        PAYSTACK.append(kw["json"]); return R({"status":True,"data":{"reference":"PSREF1","authorization_url":"https://checkout.paystack.com/abc"}})
    if "verify-number" in url: return R({"data":{"recommendation":"sell_any","servable":True,"message":"ok"}})
    raise AssertionError("unexpected http "+url)
requests.post = fake_post

from services.evosdata import core as main
from fastapi import FastAPI
from routes.evosdata import mount_evosdata
_app = FastAPI()
mount_evosdata(_app, prefix="")   # root paths, as the standalone app had them
from fastapi.testclient import TestClient
from services.evosdata import evoxera_bot as bot
assert bot._installed, "bot failed to mount"
assert any(h.__name__=="_start" for h in _app.router.on_startup), "notifier startup hook not registered"
c = TestClient(_app)

def sign(b): 
    import hmac,hashlib; return "sha256="+hmac.new(b"appsecret",b,hashlib.sha256).hexdigest()
n=[0]
def post_msg(m, phone_id="123", name="Kofi"):
    body=json.dumps({"entry":[{"changes":[{"value":{"metadata":{"phone_number_id":phone_id},
        "contacts":[{"wa_id":m["from"],"profile":{"name":name}}],"messages":[m]}}]}]}).encode()
    r=c.post("/whatsapp/cloud",content=body,headers={"X-Hub-Signature-256":sign(body),"Content-Type":"application/json"})
    assert r.status_code==200,r.text
def send(frm, kind, val, context=None, **kw):
    n[0]+=1
    if kind=="text": m={"from":frm,"id":f"m{n[0]}","type":"text","text":{"body":val}}
    elif kind=="image": m={"from":frm,"id":f"m{n[0]}","type":"image","image":{"id":"media1","caption":val}}
    else: m={"from":frm,"id":f"m{n[0]}","type":"interactive","interactive":{"list_reply":{"id":val}}}
    if context: m["context"]={"id":context}
    post_msg(m, **kw)
def alert_id_to(to_number, containing):
    for s_ in reversed(SENT):
        if s_["to"]==to_number and containing in json.dumps(s_): return s_["_id"]
    raise AssertionError("no alert")
def last(): return SENT[-1]
def texts(frm=None): 
    out=[]
    for s in SENT:
        if frm and s["to"]!=frm: continue
        out.append(s.get("text",{}).get("body") or s.get("interactive",{}).get("body",{}).get("text"))
    return out

U="233241112222"
# verification handshake
assert c.get("/whatsapp/cloud?hub.mode=subscribe&hub.verify_token=vt&hub.challenge=999").text=="999"
assert c.get("/whatsapp/cloud?hub.mode=subscribe&hub.verify_token=bad&hub.challenge=999").status_code==403
# bad signature rejected
assert c.post("/whatsapp/cloud",json={}, headers={"X-Hub-Signature-256":"sha256=00"}).status_code==403

send(U,"text","hi")
l=last()["interactive"]; assert l["type"]=="list"
assert "Hi Kofi" in l["body"]["text"] and "EVOXERA TECHNOLOGY" in l["body"]["text"]
ids=[r["id"] for r in l["action"]["sections"][0]["rows"]]; print("main menu:",ids); assert len(ids)<=10
assert "m|products" not in ids and "m|hub" in ids and "m|software" in ids
assert all(len(r["title"])<=24 for r in l["action"]["sections"][0]["rows"])

for rid,needles in [("m|evosgpt",["offline","evosgpt.xyz"]),("m|xera",["test phase","evoshub.xyz/xera","don't make claims"]),
                    ("m|about",["EVOXERA TECHNOLOGY","Creating Evolution","evoshub.xyz"]),
                    ("m|hub",["platform layer","evoshub.xyz","separate from EVOSDATA"]),
                    ("m|community",["whatsapp.com/channel"])]:
    SENT.clear(); send(U,"reply",rid); t=" ".join(x or "" for x in texts())
    assert all(nd in t for nd in needles), (rid,needles,t)
# never claims price/listing for XERA
assert "listed on" not in XT if (XT:=" ".join(x or "" for x in texts())) else True
SENT.clear(); send(U,"reply","m|software"); assert last()["interactive"]["type"]=="button" and "WhatsApp bots" in last()["interactive"]["body"]["text"]
SENT.clear(); send(U,"reply","sw|request"); assert "Tell us what" in texts()[-1]
SENT.clear(); send(U,"text","I need a CRM for my shop, budget GHS 3000")
assert any(s_["to"]=="233500000000" and "Project request" in s_["text"]["body"] and "CRM" in s_["text"]["body"] for s_ in SENT)
assert not any("Project request" in (t or "") for t in texts(U))

# keyword routing for free text
for phrase,needle in [("how much is 2gb","Current EVOSDATA prices"),("do you have an AI","EVOSGPT"),("tell me about xera token","XERA"),
                      ("i want a website built","Software development"),("what is the hub","platform layer"),("blahblah","What would you like to do")]:
    SENT.clear(); send(U,"text",phrase); t=" ".join(x or "" for x in texts()) + json.dumps(SENT)
    assert needle in t,(phrase,needle)

# prices straight from table
SENT.clear(); send(U,"reply","m|evosdata"); send(U,"reply","d|prices")
p=[t for t in texts() if t and "Current EVOSDATA prices" in t][0]; print(p); assert "AirtelTigo" in p and "2GB: GH₵ 9.00" in p

# buy flow with >10 MTN bundles -> paging
SENT.clear(); send(U,"reply","d|buy"); assert last()["interactive"]["type"]=="button"
send(U,"reply","net|MTN"); rows=last()["interactive"]["action"]["sections"][0]["rows"]
print("page1:",[r["title"] for r in rows]); assert len(rows)==10 and rows[-1]["id"].startswith("bp|MTN|1")
send(U,"reply","bp|MTN|1"); rows=last()["interactive"]["action"]["sections"][0]["rows"]; print("page2:",[r["title"] for r in rows])
send(U,"reply","net|AIRTELTIGO"); rows=last()["interactive"]["action"]["sections"][0]["rows"]; assert rows[0]["id"]=="b|AT|2GB"
send(U,"reply","net|MTN"); send(U,"reply","b|MTN|2GB")
assert "Send the number" in texts()[-1]
send(U,"text","12345"); assert "Ghana number" in texts()[-1]
send(U,"text","+233 24 123 4567")
summ=texts()[-1]; print(summ); assert "0241234567" in summ and "GH₵ 9.00" in summ and "NOT refunded" in summ
assert not DB["orders"]
send(U,"reply","pay|go")
o=DB["orders"][0]; print(o)
assert o["source"]=="whatsapp" and o["wa_number"]==U and o["phone_number"]=="0241234567" and o["status"]=="pending_payment" and o["price"]==9.0
assert PAYSTACK[0]["amount"]==900 and o["paystack_ref"]=="PSREF1" and o["evosdata_ref"].startswith("EVOS-")
assert "checkout.paystack.com/abc" in texts()[-1]
# double-tap of the same message id does nothing extra
before=len(DB["orders"])
send(U,"reply","pay|go"); assert len(DB["orders"])==before  # state already idle -> cancelled path, no new order

# the REAL paystack webhook still handles the bot's order (unchanged code path)
import hmac,hashlib
main.get_provider=lambda net:"DATAMART"
class DMR:
    def json(s): return {"data":{"orderReference":"DMREF","orderId":"77"}}
_orig=requests.post
def fp2(url,**kw):
    if "datamartgh.shop" in url and url.endswith("/purchase"): return DMR()
    return fake_post(url,**kw)
requests.post=fp2
main.process_agent_profit=lambda *a,**k:None
ev=json.dumps({"event":"charge.success","data":{"reference":"PSREF1"}}).encode()
sig=hmac.new(main.PAYSTACK_SECRET.encode(),ev,hashlib.sha512).hexdigest()
r=c.post("/webhook/paystack",content=ev,headers={"x-paystack-signature":sig,"Content-Type":"application/json"})
print("paystack webhook ->",r.json(), "order status:",o["status"]); assert o["status"]=="processing"

# notifier
SENT.clear(); bot._notify_once(); assert "Payment received" in texts(U)[-1] and o["wa_notify"]=="paid"
SENT.clear(); bot._notify_once(); assert not SENT  # no repeat
o["status"]="successful"  # what /webhook/datamart sets
SENT.clear(); bot._notify_once(); assert "Data delivered" in texts(U)[-1] and o["wa_notify"]=="done"
SENT.clear(); bot._notify_once(); assert not SENT

# tracking
SENT.clear(); send(U,"reply","m|evosdata"); send(U,"reply","d|track"); t=texts()[-2]; print(t); assert "Delivered" in t
SENT.clear(); send("233209998888","reply","d|track"); assert "don't see orders" in texts()[-1]
send("233209998888","text",o["evosdata_ref"]); assert "Delivered" in texts("233209998888")[-2]

# human handoff + owner relay (swipe-reply, @number, pause, resume)
OWNER="233500000000"
SENT.clear(); send(U,"reply","m|human")
aid=alert_id_to(OWNER,"wants to talk to a human"); assert "Kofi" in json.dumps(SENT)
assert [r for r in DB["wa_sessions"] if r["wa_number"]==U][0]["state"]=="human"
SENT.clear(); send(U,"text","are you there?")
assert SENT[-1]["to"]==OWNER and "are you there?" in SENT[-1]["text"]["body"]
assert not any(s_["to"]==U for s_ in SENT)                      # bot silent to the customer
SENT.clear(); send(U,"text","hi"); assert not any(s_["to"]==U for s_ in SENT)   # "hi" does NOT reset while paused
# owner swipe-replies to the alert -> relayed to the customer, with a menu hint on the first relay
SENT.clear(); send(OWNER,"text","Yes, how can I help?",context=aid)
rel=[s_ for s_ in SENT if s_["to"]==U]; assert rel and rel[0]["text"]["body"].startswith("Yes, how can I help?")
# owner image swipe-reply
SENT.clear(); send(OWNER,"image","here is the receipt",context=aid); assert SENT[0]["type"]=="image" and SENT[0]["to"]==U
# owner @number form
SENT.clear(); send(OWNER,"text","@0241112222 second message"); assert SENT[0]["to"]==U and "second message" in SENT[0]["text"]["body"]
# customer sends a photo while paused -> forwarded to the owner
SENT.clear(); send(U,"image","my proof"); assert SENT[-1]["to"]==OWNER and SENT[-1]["type"]=="image"
# owner resumes the bot
SENT.clear(); send(OWNER,"text","/bot",context=aid); assert any(s_["to"]==U for s_ in SENT)
assert [r for r in DB["wa_sessions"] if r["wa_number"]==U][0]["state"]=="idle"
# customer typing "menu" while paused brings the bot back
send(U,"reply","m|human"); SENT.clear(); send(U,"text","menu"); assert last()["to"]==U and last()["interactive"]["type"]=="list"
# tapping an old menu button while paused brings the bot back (and tells the owner)
send(U,"reply","m|human"); SENT.clear(); send(U,"reply","m|about")
assert any("tapped a menu button" in json.dumps(s_) for s_ in SENT if s_["to"]==OWNER) and any(s_["to"]==U for s_ in SENT)
# pause expires on its own after PAUSE_HOURS
send(U,"reply","m|human")
import datetime as _dt
[r for r in DB["wa_sessions"] if r["wa_number"]==U][0]["updated_at"]=(_dt.datetime.now(_dt.timezone.utc)-_dt.timedelta(hours=5)).isoformat()
SENT.clear(); send(U,"text","hello"); assert last()["to"]==U and last()["interactive"]["type"]=="list"
# a random non-owner cannot use relay commands
SENT.clear(); send("233209998888","text","@0241112222 hacked"); assert not any(s_["to"]==U for s_ in SENT)
SENT.clear(); send("233209998888","text","/bot 233241112222"); assert not any(s_["to"]==U for s_ in SENT)
# owner "hi" keeps alerts alive instead of showing the customer menu
SENT.clear(); send(OWNER,"text","hi"); assert "Alerts are on" in texts(OWNER)[-1]

# owner 24h-window reminder
import time as _t
own=[r for r in DB["wa_sessions"] if r["wa_number"]=="_owner"][0]
own["data"]={"last_seen":_t.time()-11*3600,"reminded":[]}
SENT.clear(); bot.check_owner_window(); assert "11 hours" not in texts(OWNER)[-1] and "10 hours" in texts(OWNER)[-1]
SENT.clear(); bot.check_owner_window(); assert not SENT                       # not repeated
own["data"]={"last_seen":_t.time()-25*3600,"reminded":[]}
SENT.clear(); bot.check_owner_window(); assert not SENT                       # window closed: nothing to send

# messages meant for another number on the same Meta app are ignored
SENT.clear(); send(U,"text","hi",phone_id="999999"); assert not SENT

# feedback
send(U,"reply","m|feedback"); SENT.clear(); send(U,"text","Page was slow"); assert any(s_["to"]==OWNER and "Page was slow" in s_["text"]["body"] for s_ in SENT)

# MTN activation hold
def fp3(url,**kw):
    if "verify-number" in url: return R({"data":{"recommendation":"activate_first","servable":False,"message":"Number must be activated"}})
    return fake_post(url,**kw)
requests.post=fp3; main._verify_cache.clear()
send(U,"reply","m|evosdata"); send(U,"reply","d|buy"); send(U,"reply","net|MTN"); send(U,"reply","b|MTN|1GB"); n_orders=len(DB["orders"])
SENT.clear(); send(U,"text","0551112233"); assert "On hold" in texts()[-1] and len(DB["orders"])==n_orders

# price changed between confirm and pay
requests.post=fake_post; main._verify_cache.clear()
send(U,"text","0241234500"); 
for r in DB["prices"]:
    if r["network"]=="MTN" and r["bundle"]=="1GB": r["price"]=6.0
SENT.clear(); send(U,"reply","pay|go"); assert "price just changed" in texts()[-1] and len(DB["orders"])==n_orders
print("\nALL BOT TESTS PASSED")
