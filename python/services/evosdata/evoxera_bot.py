"""
Evoxera Technology WhatsApp bot (Meta WhatsApp Cloud API).

Mounted at the bottom of main.py, the same way dashxera is:

    import evoxera_bot
    evoxera_bot.install(app)

It is NOT a second ordering engine. It collects the order in chat, then writes
the same `orders` row the website writes (status "pending_payment", a Paystack
reference, an EVOS- reference) plus three extra columns (source, wa_number,
wa_notify). From there the existing /webhook/paystack handler, provider
dispatch, retry jobs and provider webhooks run completely unchanged.

Customer notifications ("Payment received", "Data delivered") come from a small
background poller that watches `orders` for rows with source = 'whatsapp'.
It needs no hook inside the payment code.

Endpoints:
    GET  /whatsapp/cloud   Meta webhook verification
    POST /whatsapp/cloud   incoming messages

(The older Twilio-style /whatsapp/webhook in main.py is left alone.)

Environment (the bot stays switched off, and the API still boots, if missing):
    WA_TOKEN             permanent access token for the WhatsApp Cloud API
    WA_PHONE_NUMBER_ID   phone number id of the Evoxera Technology number
    WA_VERIFY_TOKEN      any string; must match what you type in Meta's dashboard
    WA_APP_SECRET        Meta app secret, used to verify X-Hub-Signature-256
    WA_OWNER_NUMBER      number that receives alerts and replies to customers, e.g. 233537314125
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

logger = logging.getLogger("evoxera_bot")

# ============================================================================
# CONFIG
# ============================================================================

WA_TOKEN = os.getenv("WA_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "")
WA_APP_SECRET = os.getenv("WA_APP_SECRET", "")
WA_OWNER_NUMBER = re.sub(r"\D", "", os.getenv("WA_OWNER_NUMBER", "233537314125"))
WA_GRAPH_VERSION = os.getenv("WA_GRAPH_VERSION", "v21.0")

SITE_URL = "https://evosdata.xyz"          # EVOSDATA
HUB_URL = "https://evoshub.xyz"            # EVOS Business Hub
GPT_URL = "https://evosgpt.xyz"            # EVOSGPT
XERA_URL = "https://evoshub.xyz/xera"      # XERA
COMMUNITY_URL = "https://whatsapp.com/channel/0029VaTrnsZEgGfFXkIcjt1M"
SUPPORT_URL = "https://wa.me/233537314125"
PAYSTACK_CALLBACK = "https://evosdata.xyz/success"
GUEST_EMAIL = "guest@evoshub.com"  # same placeholder the website uses for guests
COMPANY = "EVOXERA TECHNOLOGY"
TAGLINE = "Creating Evolution for the Future"

# Extra products to list under "Other products". Empty = that menu row is hidden.
# Only add entries whose details you have confirmed, e.g.
# {"id": "toptvgh", "title": "TopTVGH", "desc": "Ghanaian news platform.", "url": "https://..."}
OTHER_PRODUCTS: List[dict] = []

# Wording follows the company profile: say what is live, label what is still
# being built, never invent prices, listings, addresses or partners.
ABOUT_TEXT = (
    f"*{COMPANY}*\n_{TAGLINE}_\n\n"
    "A technology company established in 2026, building a portfolio of "
    "connected digital products:\n"
    "• EVOSDATA: data bundles and agent services\n"
    "• EVOS Business Hub: our platform layer\n"
    "• EVOSGPT: our AI product\n"
    "• XERA: digital asset and mining project\n"
    "• Software development services\n\n"
    "Each is a separate product under one company.\n"
    f"Official hub: {HUB_URL}"
)

HUB_TEXT = (
    "*EVOS Business Hub* is the platform layer of EVOXERA TECHNOLOGY: a central "
    "access point for our products and digital business tools.\n\n"
    "Its direction includes website creation and related software services, "
    "marketplace functionality, and access to EVOSGPT and XERA features as they "
    "are built out.\n\n"
    f"Official site: {HUB_URL}\n\n"
    "_The Hub is separate from EVOSDATA, which focuses on data bundles._"
)

EVOSGPT_TEXT = (
    "*EVOSGPT* is EVOXERA TECHNOLOGY's AI product, aimed at AI-powered "
    "assistance within the EVOS ecosystem.\n\n"
    "It is *offline right now* because its AI credits have run out, so it won't "
    "respond at the moment. We'll announce when it's back in our community.\n\n"
    f"Official site: {GPT_URL}\nCommunity: {COMMUNITY_URL}"
)

XERA_TEXT = (
    "*XERA* is EVOXERA TECHNOLOGY's blockchain-oriented digital asset and mining "
    "project. It is currently in its *test phase*.\n\n"
    "Work in progress includes mining-related functionality, wallet verification, "
    "BNB and TON ecosystem support, and token allocation and vesting. Token "
    "claiming and transfers will only come after successful testing.\n\n"
    "We don't make claims about price, value or exchange listings.\n\n"
    f"More: {XERA_URL}"
)

SOFTWARE_TEXT = (
    "*Software development by EVOXERA TECHNOLOGY*\n\n"
    "We build, for our own products and for external clients:\n"
    "• Websites and web applications\n"
    "• Backend APIs and integrations\n"
    "• Business automation\n"
    "• WhatsApp bots and customer communication systems\n"
    "• Custom, database-backed software and AI-assisted tools"
)

NETWORK_LABELS = {"MTN": "MTN", "TELECEL": "Telecel", "AIRTELTIGO": "AirtelTigo"}
# prices.network may hold either spelling for AirtelTigo (see CreateOrderRequest)
NETWORK_DB_VALUES = {"MTN": ["MTN"], "TELECEL": ["TELECEL"], "AIRTELTIGO": ["AIRTELTIGO", "AT"]}

SESSION_TTL_MIN = 60          # idle sessions fall back to the menu
UNPAID_AFTER_MIN = 30         # "payment not received" nudge
FAILED_AFTER_HOURS = 3        # main.py's retry job keeps trying failed orders for ~3h
POLL_SECONDS = 20
PAUSE_HOURS = 4               # bot stays quiet this long after a human takes over
OWNER_REMINDER_HOURS = (10, 15, 18)  # nudge the owner before WhatsApp's 24h window closes
LIST_MAX_ROWS = 10

router = APIRouter()


def enabled() -> bool:
    return bool(WA_TOKEN and WA_PHONE_NUMBER_ID)


# ============================================================================
# ACCESS TO main.py (resolved lazily, like dashxera, so there is no import cycle)
# ============================================================================

_MAIN_MODULE_NAME = "services.evosdata.core"


def _main():
    mod = sys.modules.get(_MAIN_MODULE_NAME)
    if mod is not None:
        return mod
    return importlib.import_module(_MAIN_MODULE_NAME)


def _db():
    return _main().supabase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(text.split(".")[0])
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ============================================================================
# WHATSAPP CLOUD API SENDERS
# ============================================================================

def _graph_url() -> str:
    return f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{WA_PHONE_NUMBER_ID}/messages"


def _post(payload: dict) -> Optional[dict]:
    """Returns Meta's JSON (always truthy on success) or None on failure."""
    if not enabled():
        logger.warning("EVOXERA BOT: WA_TOKEN / WA_PHONE_NUMBER_ID not set, not sending")
        return None
    try:
        r = requests.post(
            _graph_url(),
            headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", **payload},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        logger.error("EVOXERA BOT: send error %s", e)
        return None
    if r.status_code >= 300:
        if r.status_code in (401, 403) or '"code":190' in r.text or '"code":131005' in r.text:
            logger.error("EVOXERA BOT: TOKEN PROBLEM, generate a new System User token and update WA_TOKEN: %s", r.text[:300])
        else:
            logger.error("EVOXERA BOT: send failed %s %s", r.status_code, r.text[:300])
        return None
    try:
        return r.json() or {"ok": True}
    except ValueError:
        return {"ok": True}


def _msg_id(result: Optional[dict]) -> Optional[str]:
    try:
        return result["messages"][0]["id"]
    except Exception:
        return None


def send_text(to: str, body: str) -> Optional[dict]:
    return _post({"to": to, "type": "text", "text": {"body": body[:4000], "preview_url": True}})


def send_buttons(to: str, body: str, buttons: List[tuple]) -> Optional[dict]:
    """buttons: up to 3 of (id, title). Titles are capped at 20 chars by WhatsApp."""
    return _post({
        "to": to, "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": i, "title": t[:20]}} for i, t in buttons[:3]
            ]},
        },
    })


def send_list(to: str, body: str, button_label: str, rows: List[dict],
              header: Optional[str] = None, section_title: str = "Options") -> Optional[dict]:
    """rows: up to 10 of {id, title (24), description (72, optional)}."""
    clean = []
    for r in rows[:LIST_MAX_ROWS]:
        row = {"id": r["id"][:200], "title": r["title"][:24]}
        if r.get("description"):
            row["description"] = r["description"][:72]
        clean.append(row)
    interactive: Dict[str, Any] = {
        "type": "list",
        "body": {"text": body[:1024]},
        "action": {"button": button_label[:20],
                   "sections": [{"title": section_title[:24], "rows": clean}]},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    return _post({"to": to, "type": "interactive", "interactive": interactive})


# ============================================================================
# SESSIONS (Supabase table wa_sessions, so a restart never loses a customer)
# ============================================================================

def get_session(wa: str) -> dict:
    try:
        res = _db().table("wa_sessions").select("*").eq("wa_number", wa).limit(1).execute()
        if res.data:
            row = res.data[0]
            updated = _parse_dt(row.get("updated_at"))
            state = row.get("state") or "idle"
            limit = timedelta(hours=PAUSE_HOURS) if state == "human" else timedelta(minutes=SESSION_TTL_MIN)
            if updated and utc_now() - updated > limit:
                return {"wa_number": wa, "state": "idle", "data": {}}   # human pause or idle session expired
            return {"wa_number": wa, "state": state, "data": row.get("data") or {}}
    except Exception as e:
        logger.error("EVOXERA BOT: session read failed: %s", e)
    return {"wa_number": wa, "state": "idle", "data": {}}


def save_session(wa: str, state: str, data: Optional[dict] = None) -> None:
    try:
        _db().table("wa_sessions").upsert({
            "wa_number": wa, "state": state, "data": data or {},
            "updated_at": utc_now().isoformat(),
        }).execute()
    except Exception as e:
        logger.error("EVOXERA BOT: session save failed: %s", e)


# ============================================================================
# OWNER ALERTS (swipe-reply support) + 24h WINDOW REMINDERS
# ============================================================================
# WhatsApp only lets the bot send free-form messages to a person who messaged
# it in the last 24h. The owner is no exception, so alerts stop arriving if the
# owner stays silent for a day. Same safeguard the Nana Osompa bot uses.

OWNER_KEY = "_owner"


def notify_owner(text: str, customer: Optional[str] = None) -> bool:
    """Alert the owner. When `customer` is given, remember the alert so the owner
    can swipe-reply to it and have the reply relayed to that customer."""
    if not WA_OWNER_NUMBER:
        return False
    result = send_text(WA_OWNER_NUMBER, text)
    mid = _msg_id(result)
    if mid and customer:
        try:
            _db().table("wa_alerts").upsert({"msg_id": mid, "customer": customer,
                                             "created_at": utc_now().isoformat()}).execute()
        except Exception as e:
            logger.error("EVOXERA BOT: alert map save failed: %s", e)
    return bool(result)


def alert_customer(context_id: str) -> Optional[str]:
    if not context_id:
        return None
    try:
        res = _db().table("wa_alerts").select("customer").eq("msg_id", context_id).limit(1).execute()
        return res.data[0]["customer"] if res.data else None
    except Exception:
        return None


def mark_owner_seen() -> None:
    save_session(OWNER_KEY, "owner", {"last_seen": time.time(), "reminded": []})


def check_owner_window() -> None:
    if not WA_OWNER_NUMBER:
        return
    try:
        res = _db().table("wa_sessions").select("*").eq("wa_number", OWNER_KEY).limit(1).execute()
    except Exception:
        return
    if not res.data:
        return
    data = res.data[0].get("data") or {}
    last_seen = float(data.get("last_seen") or 0)
    if not last_seen:
        return
    hours = (time.time() - last_seen) / 3600
    if hours >= 24:
        return   # window already closed; a free-form message would fail
    reminded = list(data.get("reminded") or [])
    for stage in OWNER_REMINDER_HOURS:
        if hours >= stage and stage not in reminded:
            reminded.append(stage)
            _db().table("wa_sessions").update(
                {"data": {"last_seen": last_seen, "reminded": reminded}}
            ).eq("wa_number", OWNER_KEY).execute()
            send_text(WA_OWNER_NUMBER,
                      f"⏰ It's been about {stage} hours since you last messaged this number. "
                      "WhatsApp stops delivering alerts after 24 hours of silence.\n\n"
                      "Reply *hi* now to keep alerts coming.")
            return


# ============================================================================
# DATA HELPERS (all prices come from the live `prices` table)
# ============================================================================

def _capacity_key(bundle: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", str(bundle))
    return float(m.group(1)) if m else 1e9


def fetch_bundles(network: str) -> List[dict]:
    res = _db().table("prices").select("network, bundle, price") \
        .in_("network", NETWORK_DB_VALUES[network]).execute()
    rows = res.data or []
    rows.sort(key=lambda r: _capacity_key(r["bundle"]))
    return rows


def fetch_price(db_network: str, bundle: str) -> Optional[float]:
    res = _db().table("prices").select("price") \
        .eq("network", db_network).eq("bundle", bundle).limit(1).execute()
    return float(res.data[0]["price"]) if res.data else None


def normalise_ghana_phone(raw: str) -> Optional[str]:
    """Return a 10-digit 0XXXXXXXXX number, or None if it is not one."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("233") and len(digits) == 12:
        digits = "0" + digits[3:]
    elif len(digits) == 9:
        digits = "0" + digits
    return digits if re.fullmatch(r"0\d{9}", digits) else None


def money(v: float) -> str:
    return f"GH₵ {float(v):.2f}"


# ============================================================================
# MENUS
# ============================================================================

def show_main_menu(wa: str, greeting: bool = True, name: str = "there") -> None:
    save_session(wa, "idle")
    body = (f"👋 Hi {name}, welcome to *{COMPANY}*.\n_{TAGLINE}_\n\nWhat would you like to do?"
            if greeting else "What would you like to do?")
    rows = [
        {"id": "m|evosdata", "title": "EVOSDATA", "description": "Data bundles, prices, track orders, agents"},
        {"id": "m|hub", "title": "EVOS Business Hub", "description": "Our platform for digital business"},
        {"id": "m|evosgpt", "title": "EVOSGPT", "description": "Our AI product"},
        {"id": "m|xera", "title": "XERA", "description": "Digital asset and mining project"},
        {"id": "m|software", "title": "Software development", "description": "Websites, APIs, bots, automation"},
    ]
    if OTHER_PRODUCTS:
        rows.append({"id": "m|products", "title": "Other products"})
    rows += [
        {"id": "m|about", "title": f"About {COMPANY.title()}"[:24]},
        {"id": "m|community", "title": "Join community", "description": "Updates and announcements"},
        {"id": "m|feedback", "title": "Feedback / problem", "description": "Tell us what went wrong"},
        {"id": "m|human", "title": "Talk to a human", "description": "Chat with our team"},
    ]
    send_list(wa, body, "Open menu", rows[:LIST_MAX_ROWS], header=COMPANY, section_title="Main menu")


def show_evosdata_menu(wa: str) -> None:
    save_session(wa, "idle")
    send_list(wa, f"*EVOSDATA* is our data-bundle platform for customers, agents and resellers.\n{SITE_URL}\n\nPick an option.",
              "Choose", [
        {"id": "d|buy", "title": "Buy data", "description": "Order and pay right here"},
        {"id": "d|prices", "title": "Prices", "description": "Current bundle prices"},
        {"id": "d|track", "title": "Track my order", "description": "Check an order's status"},
        {"id": "d|agent", "title": "Become an agent", "description": "Resell data and earn"},
        {"id": "d|support", "title": "Talk to support", "description": "Chat with our team"},
        {"id": "m|menu", "title": "⬅ Main menu"},
    ], header="EVOSDATA", section_title="EVOSDATA")


def show_networks(wa: str) -> None:
    save_session(wa, "buy_network")
    send_buttons(wa, "📡 Which network?", [
        ("net|MTN", "MTN"), ("net|TELECEL", "Telecel"), ("net|AIRTELTIGO", "AirtelTigo"),
    ])


def show_bundles(wa: str, network: str, page: int = 0) -> None:
    rows = fetch_bundles(network)
    if not rows:
        send_text(wa, f"No {NETWORK_LABELS[network]} bundles are available right now. "
                      f"Please try again later or visit {SITE_URL}")
        show_evosdata_menu(wa)
        return
    per_page = LIST_MAX_ROWS - 1 if len(rows) > LIST_MAX_ROWS else LIST_MAX_ROWS
    start = page * per_page
    chunk = rows[start:start + per_page]
    items = [{"id": f"b|{r['network']}|{r['bundle']}", "title": str(r["bundle"]),
              "description": money(r["price"])} for r in chunk]
    if start + per_page < len(rows):
        items.append({"id": f"bp|{network}|{page + 1}", "title": "More bundles ➡"})
    save_session(wa, "buy_bundle", {"network": network})
    send_list(wa, f"📦 Choose your {NETWORK_LABELS[network]} bundle.", "Pick bundle", items,
              header=f"{NETWORK_LABELS[network]} bundles", section_title="Bundles")


def show_prices(wa: str) -> None:
    lines = ["💰 *Current EVOSDATA prices*"]
    try:
        for net in ("MTN", "TELECEL", "AIRTELTIGO"):
            rows = fetch_bundles(net)
            if rows:
                lines.append(f"\n*{NETWORK_LABELS[net]}*")
                lines.extend(f"{r['bundle']}: {money(r['price'])}" for r in rows)
    except Exception as e:
        logger.error("EVOXERA BOT: prices failed: %s", e)
        lines = [f"Couldn't load prices right now. See {SITE_URL}"]
    send_text(wa, "\n".join(lines))
    show_evosdata_menu(wa)


def show_software(wa: str) -> None:
    save_session(wa, "idle")
    send_buttons(wa, SOFTWARE_TEXT, [("sw|request", "Request a quote"), ("m|menu", "Main menu")])


# ============================================================================
# BUYING DATA
# ============================================================================

def ask_phone(wa: str, data: dict) -> None:
    save_session(wa, "buy_phone", data)
    send_text(wa, f"📱 Send the number that should receive the *{data['bundle']} "
                  f"{NETWORK_LABELS.get(data['network_key'], data['network'])}* data "
                  "(e.g. 0241234567).\n\nType *menu* to cancel.")


def _verify_mtn(phone: str) -> dict:
    """Reuses main.verify_number, so the shared DataMart cache and the
    2-calls-per-minute pacing are honoured. Only runs at confirm, like the site."""
    m = _main()
    try:
        fn = getattr(m.verify_number, "__wrapped__", m.verify_number)
        return fn(None, m.VerifyNumberRequest(phoneNumber=phone, network="MTN"))
    except Exception as e:
        logger.warning("EVOXERA BOT: verify failed, continuing: %s", e)
        return {"checked": False}


def handle_phone_input(wa: str, session: dict, text: str) -> None:
    data = session["data"]
    phone = normalise_ghana_phone(text)
    if not phone:
        send_text(wa, "❌ That doesn't look like a Ghana number. Send it like *0241234567*, "
                      "or type *menu* to cancel.")
        return

    if data.get("network_key") == "MTN":
        v = _verify_mtn(phone)
        if v.get("checked") and v.get("recommendation") == "activate_first":
            send_text(wa, f"⚠️ On hold: {v.get('message') or 'this MTN number needs activation first.'}\n\n"
                          "Send a different number, or type *menu*.")
            return

    price = fetch_price(data["network"], data["bundle"])
    if price is None:
        send_text(wa, "❌ That bundle is no longer available.")
        show_evosdata_menu(wa)
        return

    data.update({"phone": phone, "price": price})
    save_session(wa, "buy_confirm", data)
    send_buttons(
        wa,
        f"📦 *Order summary*\n\nNetwork: {NETWORK_LABELS.get(data['network_key'], data['network'])}\n"
        f"Bundle: {data['bundle']}\nSend to: {phone}\nPrice: {money(price)}\n\n"
        "⚠️ Please check the number. *Wrong numbers are NOT refunded.* "
        "By confirming you accept full responsibility for it.",
        [("pay|go", "Confirm & pay"), ("pay|cancel", "Cancel")],
    )


def create_whatsapp_order(wa: str, data: dict) -> Optional[dict]:
    """Writes the same order row /orders/create writes, tagged source='whatsapp'."""
    m = _main()
    price = fetch_price(data["network"], data["bundle"])
    if price is None:
        return None
    if abs(price - float(data["price"])) > 0.001:
        data["price"] = price
        data["price_changed"] = True
        return {"price_changed": True, "price": price}

    try:
        ps = requests.post(
            "https://api.paystack.co/transaction/initialize",
            headers={"Authorization": f"Bearer {m.PAYSTACK_SECRET}", "Content-Type": "application/json"},
            json={"email": GUEST_EMAIL, "amount": int(round(price * 100)), "callback_url": PAYSTACK_CALLBACK},
            timeout=10,
        ).json()
    except requests.exceptions.RequestException as e:
        logger.error("EVOXERA BOT: paystack init error: %s", e)
        return {"error": True}
    if not ps.get("status"):
        logger.error("EVOXERA BOT: paystack init rejected: %s", ps)
        return {"error": True}

    ref = ps["data"]["reference"]
    evos_ref = f"EVOS-{uuid.uuid4().hex[:8].upper()}"
    _db().table("orders").insert({
        "user_id": None,
        "guest_email": GUEST_EMAIL,
        "network": data["network"],
        "bundle": data["bundle"],
        "price": price,
        "phone_number": data["phone"],
        "paystack_ref": ref,
        "evosdata_ref": evos_ref,
        "status": "pending_payment",
        "source": "whatsapp",
        "wa_number": wa,
    }).execute()
    return {"url": ps["data"]["authorization_url"], "evos_ref": evos_ref, "price": price}


def handle_pay(wa: str, session: dict) -> None:
    data = session["data"]
    if not data.get("phone"):
        show_main_menu(wa, greeting=False)
        return
    result = create_whatsapp_order(wa, data)
    if result is None:
        send_text(wa, "❌ That bundle is no longer available.")
        show_evosdata_menu(wa)
    elif result.get("price_changed"):
        save_session(wa, "buy_confirm", data)
        send_buttons(wa, f"ℹ️ The price just changed to *{money(result['price'])}*. Continue?",
                     [("pay|go", "Confirm & pay"), ("pay|cancel", "Cancel")])
    elif result.get("error"):
        send_text(wa, "❌ Couldn't start the payment. Please try again in a moment.")
    else:
        save_session(wa, "idle")
        send_text(
            wa,
            f"💳 *Payment ready*\n\nAmount: {money(result['price'])}\nOrder: {result['evos_ref']}\n\n"
            f"Pay here:\n{result['url']}\n\n"
            "Your data is delivered automatically once payment is confirmed. "
            "I'll message you here.",
        )


# ============================================================================
# TRACKING
# ============================================================================

_STATUS_TEXT = {
    "pending_payment": "⏳ Waiting for payment",
    "paid": "💳 Paid, sending data",
    "processing": "🔄 Processing",
    "successful": "✅ Delivered",
    "failed": "❌ Failed",
}


def _order_line(o: dict) -> str:
    when = (o.get("created_at") or "")[:10]
    status = _STATUS_TEXT.get(o.get("status"), str(o.get("status")))
    return f"{o.get('bundle')} {o.get('network')} → {o.get('phone_number')}\n   {status}  ({when})  {o.get('evosdata_ref') or ''}"


def track_orders(wa: str, query: Optional[str]) -> None:
    cols = "network, bundle, phone_number, status, created_at, evosdata_ref"
    q = _db().table("orders").select(cols)
    if query:
        q_clean = query.strip()
        if q_clean.upper().startswith("EVOS-"):
            q = q.eq("evosdata_ref", q_clean.upper())
        else:
            phone = normalise_ghana_phone(q_clean)
            if not phone:
                send_text(wa, "Send an order reference (EVOS-XXXXXXXX) or a phone number, "
                              "or type *menu*.")
                return
            q = q.eq("phone_number", phone)
    else:
        q = q.eq("wa_number", wa)
    try:
        rows = q.order("created_at", desc=True).limit(5).execute().data or []
    except Exception as e:
        logger.error("EVOXERA BOT: track failed: %s", e)
        rows = []
    if rows:
        send_text(wa, "📋 *Your orders*\n\n" + "\n\n".join(_order_line(o) for o in rows))
        show_evosdata_menu(wa)
    elif query:
        send_text(wa, "I couldn't find an order for that. Check it and try again, or type *menu*.")
    else:
        save_session(wa, "track_input")
        send_text(wa, "I don't see orders made from this WhatsApp number yet.\n\n"
                      "Send an order reference (EVOS-XXXXXXXX) or the phone number you bought for.")


# ============================================================================
# HUMAN HANDOFF
# The bot goes quiet for PAUSE_HOURS while a person talks to the customer.
# The owner replies by SWIPE-REPLYING to the alert (or "@233XXXXXXXXX message").
# The customer gets the bot back by typing "menu" or tapping any old menu button.
# ============================================================================

MENU_HINT = "\n\n_(Type *menu* anytime to see our options.)_"


def norm_number(n: str) -> str:
    d = re.sub(r"\D", "", n)
    if len(d) == 10 and d.startswith("0"):
        return "233" + d[1:]
    if len(d) == 9:
        return "233" + d
    return d


def start_handoff(wa: str, name: str = "A customer", why: str = "wants to talk to a human") -> None:
    save_session(wa, "human")
    send_text(wa, "👤 Okay, someone from our team will reply here shortly.\n"
                  "(Type *menu* anytime to bring the bot back.)")
    notify_owner(f"💬 {name} (+{wa}) {why}.\n\n↩️ Swipe-reply to this message to chat with them from here.\n"
                 f"Or write: @{wa} your message", wa)


def forward_to_owner(msg: dict, name: str, wa: str) -> None:
    """Pass a customer's message to the owner while the bot is paused."""
    kind = msg.get("type")
    header = f"💬 {name} (+{wa}):"
    if kind == "text":
        notify_owner(f"{header} {msg['text']['body']}\n\n↩️ Swipe-reply to answer.", wa)
    elif kind in ("image", "document") and WA_OWNER_NUMBER:
        sent = _post({"to": WA_OWNER_NUMBER, "type": kind,
                      kind: {"id": msg[kind]["id"], "caption": f"{header} sent this\n↩️ Swipe-reply to answer."}})
        mid = _msg_id(sent)
        if mid:
            try:
                _db().table("wa_alerts").upsert({"msg_id": mid, "customer": wa,
                                                 "created_at": utc_now().isoformat()}).execute()
            except Exception:
                pass
        else:
            notify_owner(f"{header} sent a {kind} that couldn't be forwarded. Check with them directly.", wa)
    elif kind != "interactive":
        notify_owner(f"{header} sent a {kind} that can't be shown here. Check with them directly.", wa)


def handle_owner(msg: dict) -> bool:
    """Owner commands. Returns True if the message was one (and has been handled).
    Anything else from the owner is treated like a normal customer message."""
    kind = msg.get("type")
    if kind not in ("text", "image"):
        return False
    text = (msg["text"]["body"] if kind == "text" else (msg["image"].get("caption") or "")).strip()
    cust = alert_customer((msg.get("context") or {}).get("id", ""))

    mb = re.match(r"^/bot\s+(\+?\d{9,15})$", text)
    if mb:
        cust, text = norm_number(mb.group(1)), "/bot"
    else:
        m = re.match(r"^@(\+?\d{9,15})\s+(.*)$", text, re.S) or re.match(r"^/reply\s+(\+?\d{9,15})\s+(.+)$", text, re.S)
        if not cust and m:
            cust, text = norm_number(m.group(1)), m.group(2).strip()
    if not cust:
        return False

    if kind == "text" and text.lower() in ("/bot", "bot"):
        save_session(cust, "idle")
        send_text(cust, f"You're back with the {COMPANY} bot. Type *menu* to see options.")
        send_text(WA_OWNER_NUMBER, "🤖 Bot resumed for that customer.")
        return True
    if kind == "text" and not text:
        return False

    was_paused = get_session(cust)["state"] == "human"
    out = text if was_paused or not text else text + MENU_HINT
    if kind == "image":
        payload = {"to": cust, "type": "image",
                   "image": {"id": msg["image"]["id"], **({"caption": out} if out else {})}}
    else:
        payload = {"to": cust, "type": "text", "text": {"body": out}}
    if _post(payload):
        save_session(cust, "human")   # keep the bot quiet while you chat (restarts the pause)
    else:
        send_text(WA_OWNER_NUMBER, "⚠️ Couldn't deliver that. Customers can only be messaged within 24 hours "
                                   "of their last message. If it's recent, check the server logs.")
    return True


# ============================================================================
# ROUTER
# ============================================================================

# Light keyword routing for free text, so people typing "how much is 2GB" or
# "I need a website" land in the right place. Order matters: first match wins.
KEYWORD_ROUTES = [
    (r"\b(human|person|someone|representative|support|talk to)\b", "m|human"),
    (r"\b(price|prices|cost|how much|rate|rates)\b", "d|prices"),
    (r"\b(track|status|my order|delivered|delivery)\b", "d|track"),
    (r"\b(reseller|resell|agent|agents)\b", "d|agent"),
    (r"\b(data|bundle|bundles|mtn|telecel|airteltigo|airtel)\b", "m|evosdata"),
    (r"\b(gpt|ai|chatbot|artificial)\b", "m|evosgpt"),
    (r"\b(xera|token|mining|mine|wallet|crypto|coin)\b", "m|xera"),
    (r"\b(hub|marketplace)\b", "m|hub"),
    (r"\b(website|web app|app|software|develop|developer|api|automation|bot|quote)\b", "m|software"),
    (r"\b(about|company|who are you|evoxera)\b", "m|about"),
]


def keyword_target(text: str) -> Optional[str]:
    low = text.lower()
    for pattern, target in KEYWORD_ROUTES:
        if re.search(pattern, low):
            return target
    return None


def handle_incoming(msg: dict, name: str = "there") -> None:
    """All user text is treated as data, never as instructions."""
    wa = re.sub(r"\D", "", msg.get("from", ""))
    kind = msg.get("type")
    try:
        text, reply_id = "", ""
        if kind == "text":
            text = (msg.get("text") or {}).get("body", "").strip()
        elif kind == "interactive":
            inter = msg.get("interactive") or {}
            reply_id = (inter.get("list_reply") or inter.get("button_reply") or {}).get("id", "")
        low = text.lower()

        # ---- owner: relay commands first, then "hi" keeps alerts alive ----
        if wa == WA_OWNER_NUMBER:
            mark_owner_seen()
            if handle_owner(msg):
                return
            if kind == "text" and low in ("hi", "hello", "hey"):
                send_text(wa, "✅ Alerts are on for the next 24 hours. Type *menu* to see the customer menu.")
                return

        session = get_session(wa)
        state = session["state"]

        # ---- human mode: stay silent and pass messages on ----
        if state == "human":
            if kind == "interactive":                # tapping an old menu button brings the bot back
                save_session(wa, "idle")
                notify_owner(f"🤖 {name} (+{wa}) tapped a menu button, so the bot is active for them again.\n\n"
                             "↩️ Swipe-reply to chat (this pauses the bot again).", wa)
                session = {"wa_number": wa, "state": "idle", "data": {}}
                state = "idle"
            elif low == "menu":
                return show_main_menu(wa, name=name)
            else:
                return forward_to_owner(msg, name, wa)

        if kind == "interactive":
            return route_reply(wa, session, reply_id, name)

        if kind != "text":   # images, stickers, audio...
            send_text(wa, "Sorry, I only understand text and menu options for now 🙏")
            return show_main_menu(wa, greeting=False, name=name)

        if low in ("menu", "start", "hi", "hello", "hey", "0", "cancel"):
            return show_main_menu(wa, name=name)

        if state == "buy_phone":
            return handle_phone_input(wa, session, text)
        if state == "track_input":
            return track_orders(wa, text)
        if state == "feedback":
            notify_owner(f"📝 Feedback from {name} (+{wa}):\n{text}\n\n↩️ Swipe-reply to respond.", wa)
            send_text(wa, "Thank you, we've received it ✅")
            return show_main_menu(wa, greeting=False, name=name)
        if state == "project":
            notify_owner(f"🛠 *Project request* from {name} (+{wa}):\n{text}\n\n↩️ Swipe-reply to respond.", wa)
            send_text(wa, "Thanks! We've received your request and will get back to you here shortly ✅")
            return show_main_menu(wa, greeting=False, name=name)

        target = keyword_target(text)
        if target:
            return route_reply(wa, session, target, name)
        show_main_menu(wa, name=name)
    except Exception as e:  # never let one bad message kill the handler
        logger.exception("EVOXERA BOT: handler error: %s", e)
        try:
            send_text(wa, "Something went wrong on our side. Type *menu* to start again.")
        except Exception:
            pass


def route_reply(wa: str, session: dict, rid: str, name: str = "there") -> None:
    parts = rid.split("|")
    tag = parts[0]

    if tag == "m":
        action = parts[1] if len(parts) > 1 else ""
        if action == "menu":
            return show_main_menu(wa, greeting=False, name=name)
        if action == "evosdata":
            return show_evosdata_menu(wa)
        if action in ("evosgpt", "xera", "hub", "about"):
            send_text(wa, {"evosgpt": EVOSGPT_TEXT, "xera": XERA_TEXT, "hub": HUB_TEXT, "about": ABOUT_TEXT}[action])
            return show_main_menu(wa, greeting=False, name=name)
        if action == "software":
            return show_software(wa)
        if action == "community":
            send_text(wa, f"👥 Join the {COMPANY} community:\n{COMMUNITY_URL}")
            return show_main_menu(wa, greeting=False, name=name)
        if action == "feedback":
            save_session(wa, "feedback")
            return send_text(wa, "📝 Tell us what happened or what we can improve. "
                                 "Send it as one message (or type *menu* to cancel).")
        if action == "human":
            return start_handoff(wa, name)
        if action == "products" and OTHER_PRODUCTS:
            save_session(wa, "idle")
            return send_list(wa, "Which product would you like to know about?", "Choose", [
                {"id": f"p|{p['id']}", "title": p["title"], "description": p["desc"]}
                for p in OTHER_PRODUCTS
            ] + [{"id": "m|menu", "title": "⬅ Main menu"}], header="Other products",
                section_title="Products")

    elif tag == "p":
        product = next((p for p in OTHER_PRODUCTS if p["id"] == parts[1]), None)
        if product:
            link = product["url"] or "Link not available yet."
            send_text(wa, f"*{product['title']}*\n{product['desc']}\n\n{link}")
        return show_main_menu(wa, greeting=False, name=name)

    elif tag == "sw":
        if parts[1] == "request":
            save_session(wa, "project")
            return send_text(wa, "🛠 Tell us what you'd like built (what it should do, and a budget range "
                                 "if you have one). Send it as one message, or type *menu* to cancel.")

    elif tag == "d":
        action = parts[1]
        if action == "buy":
            return show_networks(wa)
        if action == "prices":
            return show_prices(wa)
        if action == "track":
            return track_orders(wa, None)
        if action == "agent":
            send_text(wa, "💼 *Become an EVOSDATA agent*\n\nResell data under your own store and "
                          f"earn on every sale.\n\nRegister: {SITE_URL}/register\n"
                          f"Questions: {SUPPORT_URL}?text=Hi, I'd like to become an EVOS agent")
            return show_evosdata_menu(wa)
        if action == "support":
            return start_handoff(wa, name, "needs EVOSDATA support")

    elif tag == "net" and parts[1] in NETWORK_LABELS:
        return show_bundles(wa, parts[1])

    elif tag == "bp" and len(parts) == 3 and parts[1] in NETWORK_LABELS:
        return show_bundles(wa, parts[1], int(parts[2]) if parts[2].isdigit() else 0)

    elif tag == "b" and len(parts) == 3:
        db_network, bundle = parts[1], parts[2]
        key = next((k for k, v in NETWORK_DB_VALUES.items() if db_network in v), None)
        if key and fetch_price(db_network, bundle) is not None:
            return ask_phone(wa, {"network": db_network, "network_key": key, "bundle": bundle})
        send_text(wa, "❌ That bundle is no longer available.")
        return show_evosdata_menu(wa)

    elif tag == "pay":
        if parts[1] == "go" and session["state"] == "buy_confirm":
            return handle_pay(wa, session)
        send_text(wa, "Order cancelled.")
        return show_main_menu(wa, greeting=False, name=name)

    show_main_menu(wa, name=name)


# ---------- webhook endpoints ----------

def _verify_signature(body: bytes, header: str) -> bool:
    if not WA_APP_SECRET:
        return True  # signature check is opt-in; set WA_APP_SECRET to enforce it
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(WA_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


_seen: Dict[str, float] = {}


def _already_seen(msg_id: str) -> bool:
    """Meta retries deliveries; drop repeats of the same message id."""
    now = time.time()
    for k in [k for k, t in _seen.items() if now - t > 600]:
        _seen.pop(k, None)
    if msg_id in _seen:
        return True
    _seen[msg_id] = now
    return False


@router.get("/whatsapp/cloud")
def whatsapp_verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and WA_VERIFY_TOKEN and \
            hmac.compare_digest(q.get("hub.verify_token", ""), WA_VERIFY_TOKEN):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "Forbidden")


@router.post("/whatsapp/cloud")
async def whatsapp_incoming(request: Request, background: BackgroundTasks):
    body = await request.body()
    if not _verify_signature(body, request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(403, "Bad signature")
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            # If several WhatsApp numbers share one Meta app they share one webhook URL.
            # Only act on messages that were sent to THIS bot's number.
            to_id = (value.get("metadata") or {}).get("phone_number_id")
            if WA_PHONE_NUMBER_ID and to_id and to_id != WA_PHONE_NUMBER_ID:
                continue
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name", "there")
                     for c in value.get("contacts", []) or []}
            for msg in value.get("messages", []) or []:
                msg_id = msg.get("id", "")
                if msg_id and _already_seen(msg_id):
                    continue
                background.add_task(handle_incoming, msg, names.get(msg.get("from"), "there"))
    return {"status": "ok"}


# ============================================================================
# ORDER NOTIFIER (replaces a hook inside the payment code)
# stages: None -> 'unpaid' -> 'paid' -> 'done'
# ============================================================================

def _notify_once() -> None:
    since = (utc_now() - timedelta(days=3)).isoformat()
    rows = _db().table("orders") \
        .select("id, status, bundle, network, phone_number, price, evosdata_ref, wa_number, wa_notify, created_at") \
        .eq("source", "whatsapp") \
        .gte("created_at", since) \
        .or_("wa_notify.is.null,wa_notify.neq.done") \
        .execute().data or []

    for o in rows:
        wa, stage, status = o.get("wa_number"), o.get("wa_notify"), o.get("status")
        if not wa:
            continue
        age = utc_now() - (_parse_dt(o.get("created_at")) or utc_now())
        label = f"{o['bundle']} {o['network']} → {o['phone_number']}"
        new_stage, message = None, None

        if status == "successful":
            new_stage, message = "done", f"✅ *Data delivered!*\n{label}\nOrder: {o.get('evosdata_ref')}\n\nThank you for choosing EvosData."
        elif status in ("paid", "processing") and stage not in ("paid", "done"):
            new_stage, message = "paid", f"💳 *Payment received.*\nSending {label} now. I'll confirm when it lands."
        elif status == "failed" and age > timedelta(hours=FAILED_AFTER_HOURS):
            new_stage, message = "done", (f"❌ We couldn't deliver {label} (order {o.get('evosdata_ref')}). "
                                          f"Please contact support so we can sort it out: {SUPPORT_URL}")
        elif status == "pending_payment" and stage is None and age > timedelta(minutes=UNPAID_AFTER_MIN):
            new_stage, message = "unpaid", (f"⏳ We haven't received payment for {label} yet. "
                                            "If you didn't complete it, just start a new order from the menu.")

        if message and new_stage:
            # claim the stage first so a slow send can't double-notify
            _db().table("orders").update({"wa_notify": new_stage}).eq("id", o["id"]).execute()
            send_text(wa, message)


async def _notifier_loop() -> None:
    tick = 0
    while True:
        try:
            if enabled():
                await asyncio.to_thread(_notify_once)
                if tick % 15 == 0:   # about every 5 minutes
                    await asyncio.to_thread(check_owner_window)
        except Exception as e:
            logger.error("EVOXERA BOT: notifier error: %s", e)
        tick += 1
        await asyncio.sleep(POLL_SECONDS)


_installed = False


def install(app) -> None:
    global _installed
    app.include_router(router)

    async def _start():
        asyncio.create_task(_notifier_loop())

    # Same hook main.py already uses for its own background jobs. (Starlette
    # removed app.add_event_handler, so don't use that.)
    app.on_event("startup")(_start)
    _installed = True
    logger.info("EVOXERA BOT: mounted at /whatsapp/cloud (enabled=%s)", enabled())
