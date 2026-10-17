"""
Spin to Win (EVOS Data).

Mounted at the bottom of main.py, the same way dashxera and the WhatsApp bot are:

    import spin
    spin.install(app)

Rules (as agreed with the owner):
  * One spin per user per UTC day. The unique (user_id, spin_date) constraint on
    `spins` is the limit, so two simultaneous requests cannot both spin. It resets
    at 00:00 UTC, which is midnight in Ghana.
  * The wheel alternates 1GB, Try again, 2GB, Try again ... 10GB, Try again.
  * The SERVER picks the result. Odds per spin (see PRIZE_ODDS):
        normal user ........ 1GB 1%, then 0.5% ... down to 10GB 0.05% (about 1 in 2,000)
        after a 3GB+ buy ... 1GB 25%, bigger prizes unchanged
    The boost is hidden: it is worked out here from the user's own orders and each
    qualifying purchase boosts exactly one spin (spin_boost_orders).
  * A daily cap on total GB given away (SPIN_DAILY_CAP_GB, default 50). Once it is
    reached the wheel can only land on "Try again" until the next UTC day.
  * A win must be claimed with a phone number and a network. Telecel/Vodafone
    bundles start at 10GB, so Telecel is only allowed for a 10GB prize.
  * A claim creates a normal `orders` row (source 'spin', price 0) and dispatches it
    through the same provider helpers as a paid order. If the first dispatch fails the
    row stays 'processing' with no provider reference, which is exactly what the
    existing retry_stuck_orders() job picks up, so retries/escalation are shared.

Endpoints (all need X-User-Token, issued at login):
    GET  /spin/status?user_id=
    POST /spin          {user_id}
    POST /spin/claim    {user_id, spin_id, phone, network}
"""


from __future__ import annotations

import importlib
import logging
import os
import random
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.evosdata import datamart_stock

logger = logging.getLogger("spin")

# ============================================================================
# CONFIG
# ============================================================================

# (prize GB, % chance for a normal spin, % chance after a 3GB+ purchase)
PRIZE_ODDS = [
    (1, 1.00, 25.00),
    (2, 0.50, 0.50),
    (3, 0.40, 0.40),
    (4, 0.30, 0.30),
    (5, 0.25, 0.25),
    (6, 0.20, 0.20),
    (7, 0.15, 0.15),
    (8, 0.12, 0.12),
    (9, 0.10, 0.10),
    (10, 0.05, 0.05),
]

# Wheel layout: 1GB, Try again, 2GB, Try again, ... 10GB, Try again (20 segments).
SEGMENTS: List[Optional[int]] = []
for _gb, _, _ in PRIZE_ODDS:
    SEGMENTS += [_gb, None]

DAILY_CAP_GB = int(os.getenv("SPIN_DAILY_CAP_GB", "50"))
BOOST_MIN_GB = 3             # a purchase of this size or more boosts the next spin
BOOST_WINDOW_HOURS = 48      # how long a qualifying purchase stays usable
CLAIM_WINDOW_DAYS = 7        # an unclaimed win expires after this
TELECEL_MIN_PRIZE_GB = 10    # Telecel/Vodafone bundles start at 10GB

NETWORKS = ("MTN", "AIRTELTIGO", "TELECEL")
_PRICE_NETWORK_ALIASES = {"MTN": ["MTN"], "AIRTELTIGO": ["AIRTELTIGO", "AT"], "TELECEL": ["TELECEL"]}
_PAID_STATUSES = ["paid", "processing", "successful", "delivered"]

_rng = random.SystemRandom()

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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return _now().date().isoformat()


def _next_reset() -> str:
    d = _now().date() + timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat()


def _parse_dt(raw: str) -> datetime:
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ============================================================================
# PURE LOGIC (unit-testable, no database)
# ============================================================================

def parse_gb(bundle: str) -> float:
    """'3GB' -> 3.0, '500MB' -> 0.488, anything unparseable -> 0."""
    m = re.match(r"\s*([\d.]+)\s*(GB|MB)?", str(bundle or "").upper())
    if not m:
        return 0.0
    try:
        n = float(m.group(1))
    except ValueError:
        return 0.0
    return n / 1024 if m.group(2) == "MB" else n


def pick_prize(boosted: bool, budget_left_gb: float, roll: Optional[float] = None) -> Optional[int]:
    """Return the prize in GB, or None for 'Try again'. `roll` (0-100) is injectable for tests."""
    if roll is None:
        roll = _rng.random() * 100
    acc = 0.0
    for gb, normal, boosted_pct in PRIZE_ODDS:
        acc += boosted_pct if boosted else normal
        if roll < acc:
            return gb if gb <= budget_left_gb else None   # daily cap: land on Try again
    return None


def segment_for(prize_gb: Optional[int]) -> int:
    """Which wheel segment the pointer should stop on."""
    if prize_gb is None:
        return _rng.choice([i for i, s in enumerate(SEGMENTS) if s is None])
    return SEGMENTS.index(prize_gb)


def network_rule_ok(network: str, prize_gb: int) -> bool:
    """Telecel/Vodafone only for the 10GB prize; MTN and AirtelTigo for any prize."""
    if network == "TELECEL":
        return prize_gb >= TELECEL_MIN_PRIZE_GB
    return network in NETWORKS


# ============================================================================
# DATABASE HELPERS
# ============================================================================

def _find_bundle(network: str, gb: int) -> Optional[dict]:
    """The row in `prices` for this network that is exactly `gb` GB, or None.
    Prizes are only offered on bundles you actually sell (so a provider can deliver them)."""
    for alias in _PRICE_NETWORK_ALIASES.get(network, [network]):
        res = _db().table("prices").select("network,bundle").eq("network", alias).execute()
        for row in res.data or []:
            if abs(parse_gb(row.get("bundle")) - gb) < 1e-9 and "MB" not in str(row.get("bundle", "")).upper():
                return row
    return None


def available_networks(prize_gb: int) -> Dict[str, dict]:
    out = {}
    for net in NETWORKS:
        if not network_rule_ok(net, prize_gb):
            out[net] = {"available": False, "reason": f"Starts at {TELECEL_MIN_PRIZE_GB}GB"}
        elif not _find_bundle(net, prize_gb):
            out[net] = {"available": False, "reason": f"{prize_gb}GB not available"}
        else:
            out[net] = {"available": True, "reason": None}
    return out


def _given_today_gb() -> float:
    res = _db().table("spins").select("prize_gb").eq("spin_date", _today()).execute()
    return float(sum((r.get("prize_gb") or 0) for r in (res.data or [])))


def _find_boost_order(user_id: int) -> Optional[int]:
    """Oldest unused paid order of BOOST_MIN_GB+ from the last BOOST_WINDOW_HOURS, or None."""
    cutoff = (_now() - timedelta(hours=BOOST_WINDOW_HOURS)).isoformat()
    orders = (_db().table("orders")
              .select("id,bundle,status,source,created_at")
              .eq("user_id", user_id)
              .in_("status", _PAID_STATUSES)
              .gte("created_at", cutoff)
              .order("created_at")
              .execute().data or [])
    used = {r["order_id"] for r in (_db().table("spin_boost_orders").select("order_id")
                                    .eq("user_id", user_id).execute().data or [])}
    for o in orders:
        if o.get("source") == "spin" or o["id"] in used:
            continue
        if parse_gb(o.get("bundle")) >= BOOST_MIN_GB:
            return o["id"]
    return None


def _pending_prize(user_id: int) -> Optional[dict]:
    """The user's newest unclaimed win, expiring it first if it is past the claim window."""
    rows = (_db().table("spins").select("*").eq("user_id", user_id).eq("status", "won")
            .order("created_at", desc=True).limit(1).execute().data or [])
    if not rows:
        return None
    row = rows[0]
    if _now() - _parse_dt(row["created_at"]) > timedelta(days=CLAIM_WINDOW_DAYS):
        _db().table("spins").update({"status": "expired"}).eq("id", row["id"]).eq("status", "won").execute()
        return None
    return {"spin_id": row["id"], "prize_gb": row["prize_gb"],
            "networks": available_networks(int(row["prize_gb"]))}


# ============================================================================
# DISPATCH (mirrors the Paystack webhook, for a single reward order)
# ============================================================================

def _dispatch(order: dict) -> dict:
    """Send a reward order to the highest-priority provider. Returns the columns to store.
    Raises on any failure; the caller leaves the order 'processing' for retry_stuck_orders()."""
    import requests
    m = _main()
    provider = m.get_provider(order["network"])
    ref = order["paystack_ref"]

    if provider == "DATAMART":
        r = datamart_stock.purchase_post(
            f"{m.DATAMART_BASE}/purchase",
            headers={"X-API-Key": m.DATAMART_API_KEY},
            json={"phoneNumber": order["phone_number"], "network": m.NETWORK_MAP.get(order["network"]),
                  "capacity": m.extract_capacity(order["bundle"]), "gateway": "wallet"},
            timeout=m.REQUEST_TIMEOUT,
        ).json()
        d = r.get("data", {}) or {}
        if not d.get("orderReference"):
            raise RuntimeError(f"DATAMART rejected: {r}")
        return {"datamart_ref": d.get("orderReference"), "datamart_order_id": d.get("orderId")}

    if provider == "BUNDLES_GHANA":
        names = {"MTN": "MTN", "TELECEL": "Telecel", "AIRTELTIGO": "AirtelTigo", "AT": "AirtelTigo"}
        net = names.get(order["network"].upper(), order["network"])
        bundles = m.call_bundles_ghana(f"/bundles?network={net}")
        if not bundles.get("success"):
            raise RuntimeError(f"BG fetch failed: {bundles.get('error')}")
        vol = order["bundle"].upper().replace(" ", "")
        match = next((b for b in bundles.get("bundles", [])
                      if b.get("volume", "").upper().replace(" ", "") == vol and b.get("status") == "active"), None)
        if not match:
            raise RuntimeError(f"No active BG bundle for {net} {vol}")
        o = m.call_bundles_ghana("/order", method="POST", body={
            "bundle_id": match["id"], "phone": order["phone_number"],
            "webhook_url": "https://api.evosdata.xyz/webhook/bundlesghana"})
        if not o.get("success"):
            raise RuntimeError(f"BG order failed: {o.get('error', o.get('message'))}")
        return {"datamart_ref": o["order"]["reference"], "datamart_order_id": str(o["order"]["id"])}

    if provider == "SWIFT_DATA_LINK":
        sdl = m.call_swift_data_link(network=order["network"],
                                     volume=float(m.extract_capacity(order["bundle"]) or 0),
                                     phone=order["phone_number"])
        if not sdl.get("success"):
            raise RuntimeError(f"SDL order failed: {sdl.get('error', sdl)}")
        return {"datamart_ref": sdl.get("reference"), "datamart_order_id": sdl.get("orderId")}

    if provider == "AGYEKUMDATA":
        pkg = m.get_agyekumdata_package_id(order["network"], order["bundle"])
        agd = m.call_agyekumdata_purchase(package_id=pkg, phone=order["phone_number"], client_reference=ref)
        if not agd.get("success"):
            raise RuntimeError(f"AGYEKUMDATA order failed: {agd.get('error', agd)}")
        d = agd.get("data", {}) or {}
        return {"datamart_ref": d.get("clientReference") or m.sanitise_agyekumdata_ref(ref),
                "datamart_order_id": d.get("orderId")}

    raise RuntimeError("No provider assigned")


# ============================================================================
# API
# ============================================================================

router = APIRouter(prefix="/spin", tags=["spin"])


class SpinBody(BaseModel):
    user_id: int


class ClaimBody(BaseModel):
    user_id: int
    spin_id: int
    phone: str
    network: str


def _labels() -> List[str]:
    return [f"{s}GB" if s else "Try again" for s in SEGMENTS]


@router.get("/status")
def spin_status(request: Request, user_id: int):
    _main().require_user(request, user_id)
    today = (_db().table("spins").select("id,prize_gb,status").eq("user_id", user_id)
             .eq("spin_date", _today()).limit(1).execute().data or [])
    return {
        "status": "ok",
        "can_spin": not today,
        "next_reset_at": _next_reset(),
        "segments": _labels(),
        "today": ({"prize_gb": today[0].get("prize_gb"), "won": today[0].get("prize_gb") is not None}
                  if today else None),
        "pending_prize": _pending_prize(user_id),
    }


@router.post("")
def do_spin(request: Request, body: SpinBody):
    m = _main()
    user_id = m.require_user(request, body.user_id)
    db = _db()

    if not (db.table("users").select("id").eq("id", user_id).limit(1).execute().data):
        raise HTTPException(404, "User not found")

    def already():
        return {"status": "already_spun", "can_spin": False, "next_reset_at": _next_reset(),
                "pending_prize": _pending_prize(user_id)}

    today = _today()
    if db.table("spins").select("id").eq("user_id", user_id).eq("spin_date", today).limit(1).execute().data:
        return already()

    # Reserve the boost first: the primary key on order_id means one purchase boosts one spin.
    boost_order = _find_boost_order(user_id)
    if boost_order is not None:
        try:
            db.table("spin_boost_orders").insert({"order_id": boost_order, "user_id": user_id}).execute()
        except Exception:
            boost_order = None   # lost a race for that order: spin unboosted

    prize = pick_prize(boost_order is not None, DAILY_CAP_GB - _given_today_gb())

    try:
        ins = db.table("spins").insert({
            "user_id": user_id, "spin_date": today, "prize_gb": prize,
            "boosted": boost_order is not None, "boost_order_id": boost_order,
            "status": "won" if prize else "lost",
        }).execute()
        spin = ins.data[0]
    except Exception as e:
        # The unique (user_id, spin_date) constraint fired: a parallel request already spun.
        logger.info("SPIN: insert refused for user %s (%s)", user_id, e)
        if boost_order is not None:
            db.table("spin_boost_orders").delete().eq("order_id", boost_order).execute()
        return already()

    if boost_order is not None:
        db.table("spin_boost_orders").update({"spin_id": spin["id"]}).eq("order_id", boost_order).execute()

    # Cap re-check: two users winning at the same instant could jointly pass the cap.
    if prize and _given_today_gb() > DAILY_CAP_GB:
        db.table("spins").update({"prize_gb": None, "status": "lost"}).eq("id", spin["id"]).execute()
        prize = None
        logger.warning("SPIN: daily cap %sGB hit, spin %s downgraded to Try again", DAILY_CAP_GB, spin["id"])

    logger.info("SPIN: user=%s prize=%s boosted=%s", user_id, prize, boost_order is not None)
    return {
        "status": "ok",
        "spin_id": spin["id"],
        "won": prize is not None,
        "prize_gb": prize,
        "segment_index": segment_for(prize),
        "networks": available_networks(prize) if prize else None,
        "next_reset_at": _next_reset(),
    }


@router.post("/claim")
def claim_prize(request: Request, body: ClaimBody):
    m = _main()
    user_id = m.require_user(request, body.user_id)
    db = _db()

    network = body.network.strip().upper()
    if network in ("VODAFONE", "VODA"):
        network = "TELECEL"
    if network not in NETWORKS:
        raise HTTPException(400, "Choose MTN, AirtelTigo or Telecel")
    phone = m.normalise_phone(body.phone)

    rows = db.table("spins").select("*").eq("id", body.spin_id).eq("user_id", user_id).limit(1).execute().data
    if not rows:
        raise HTTPException(404, "Prize not found")
    spin = rows[0]
    if spin["status"] == "claimed":
        raise HTTPException(409, "This prize was already claimed")
    if spin["status"] != "won" or not spin.get("prize_gb"):
        raise HTTPException(400, "Nothing to claim")
    if _now() - _parse_dt(spin["created_at"]) > timedelta(days=CLAIM_WINDOW_DAYS):
        db.table("spins").update({"status": "expired"}).eq("id", spin["id"]).execute()
        raise HTTPException(410, "This prize has expired")

    gb = int(spin["prize_gb"])
    if not network_rule_ok(network, gb):
        raise HTTPException(400, f"Telecel/Vodafone starts at {TELECEL_MIN_PRIZE_GB}GB. Pick MTN or AirtelTigo for this prize.")
    bundle_row = _find_bundle(network, gb)
    if not bundle_row:
        raise HTTPException(400, f"{gb}GB is not available on that network right now. Pick another network.")

    # Atomic claim: only the request whose update actually changes the row goes on.
    claim = (db.table("spins")
             .update({"status": "claimed", "claim_phone": phone, "claim_network": network,
                      "claimed_at": _now().isoformat()})
             .eq("id", spin["id"]).eq("status", "won").execute())
    if not claim.data:
        raise HTTPException(409, "This prize was already claimed")

    evos_ref = f"EVOS-{uuid.uuid4().hex[:8].upper()}"
    paystack_ref = f"EVOS-SPIN-{spin['id']}-{uuid.uuid4().hex[:6].upper()}"
    try:
        ins = db.table("orders").insert({
            "user_id": user_id, "guest_email": None, "network": network, "bundle": bundle_row["bundle"],
            "price": 0, "phone_number": phone, "paystack_ref": paystack_ref, "evosdata_ref": evos_ref,
            "status": "processing", "source": "spin",
        }).execute()
        order = ins.data[0]
    except Exception as e:
        logger.error("SPIN CLAIM: order insert failed for spin %s: %s", spin["id"], e)
        # Give the prize back so the user can try the claim again.
        db.table("spins").update({"status": "won", "claim_phone": None, "claim_network": None,
                                  "claimed_at": None}).eq("id", spin["id"]).execute()
        raise HTTPException(500, "Could not create your prize order. Please try again.")

    db.table("spins").update({"order_id": order["id"]}).eq("id", spin["id"]).execute()

    delivery = "queued"
    try:
        fields = _dispatch(order)
        db.table("orders").update(fields).eq("id", order["id"]).execute()
        delivery = "sent"
    except Exception as e:
        # Left 'processing' with no provider ref: retry_stuck_orders() picks it up after 10 minutes.
        logger.error("SPIN CLAIM: first dispatch of order %s failed (%s) - retry job will handle it", order["id"], e)

    return {"status": "claimed", "delivery": delivery, "prize_gb": gb, "network": network,
            "phone": phone, "reference": evos_ref}


_installed = False


def install(app) -> None:
    global _installed
    app.include_router(router)
    _installed = True
    logger.info("SPIN: mounted at /spin (daily cap %sGB)", DAILY_CAP_GB)
