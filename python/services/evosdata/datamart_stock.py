"""
DataMart wallet -> automatic out-of-stock.

Every few minutes the wallet balance is read from DataMart (GET /balance). A
bundle is "in stock" only while the wallet can cover its selling price (the
`prices.price` figure, the one customers pay) plus a small safety buffer.
Bundles the wallet can't cover show as out of stock and can't be ordered, on
every channel, until a later check sees a bigger balance (top-up).

Failure policy: if DataMart can't be reached, or the last good reading is older
than STALE_AFTER_SECONDS, stock gating switches OFF (everything sells as
normal). A DataMart outage must never shut the whole shop on its own; the
failure is logged and shown on the DashXera panel instead.

Tables (see 20261017_datamart_wallet.sql):
    datamart_wallet      one row (id=1): latest balance + check metadata
    datamart_wallet_log  one row each time the balance changes
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

logger = logging.getLogger("datamart_stock")

DATAMART_BASE = "https://api.datamartgh.shop/api/developer"

POLL_SECONDS = max(60, int(os.getenv("DATAMART_BALANCE_POLL_SECONDS", "300")))
BUFFER_GHS = float(os.getenv("DATAMART_STOCK_BUFFER_GHS", "2"))
STALE_AFTER_SECONDS = int(os.getenv("DATAMART_BALANCE_STALE_SECONDS", "1800"))
LOW_BALANCE_GHS = float(os.getenv("DATAMART_LOW_BALANCE_GHS", "50"))
REQUEST_TIMEOUT = 10
_CACHE_TTL = 15          # seconds the wallet row is cached per process
_PRICE_TTL = 30          # seconds the price table is cached per process

_lock = threading.Lock()
_wallet_cache: Dict = {"ts": 0.0, "row": None}
_price_cache: Dict = {"ts": 0.0, "map": {}}
_refresh_lock = threading.Lock()
RECHECK_MIN_GAP = float(os.getenv("DATAMART_RECHECK_MIN_GAP_SECONDS", "10"))
RECHECK_SETTLE = 2.0     # seconds to let DataMart finish debiting before reading
_recheck_lock = threading.Lock()
_recheck_state: Dict = {"last": 0.0, "timer": None}


def _db():
    from services.evosdata.db import get_supabase   # lazy: keeps this module import-light
    return get_supabase()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(raw) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ============================================================================
# DATAMART CALL
# ============================================================================

def fetch_remote_balance() -> float:
    """GET {DATAMART_BASE}/balance. Raises on any failure."""
    key = os.getenv("DATAMART_API_KEY", "")
    if not key:
        raise RuntimeError("DATAMART_API_KEY is not set")
    resp = requests.get(f"{DATAMART_BASE}/balance", headers={"X-API-Key": key}, timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"DataMart /balance returned {resp.status_code}: {resp.text[:120]}")
    body = resp.json() or {}
    if body.get("status") != "success":
        raise RuntimeError(f"DataMart /balance rejected: {str(body)[:120]}")
    bal = _num((body.get("data") or {}).get("balance"))
    if bal is None or bal < 0:
        raise RuntimeError("DataMart /balance returned no usable balance")
    return round(bal, 2)


# ============================================================================
# STATE
# ============================================================================

def _clear_cache() -> None:
    with _lock:
        _wallet_cache["ts"] = 0.0


def get_wallet(force: bool = False) -> Optional[dict]:
    """Latest wallet row, cached briefly. None if never checked or unreadable."""
    now = time.time()
    with _lock:
        if not force and now - _wallet_cache["ts"] < _CACHE_TTL:
            return _wallet_cache["row"]
    try:
        res = _db().table("datamart_wallet").select("*").eq("id", 1).limit(1).execute()
        row = res.data[0] if res.data else None
    except Exception as exc:
        logger.warning("DATAMART STOCK: couldn't read wallet row (%s) — gating off", exc)
        row = None
    with _lock:
        _wallet_cache["row"] = row
        _wallet_cache["ts"] = now
    return row


def gating_active(wallet: Optional[dict]) -> bool:
    """True only when there is a fresh, successful balance reading."""
    if not wallet:
        return False
    bal = _num(wallet.get("balance"))
    ok_at = _parse_dt(wallet.get("last_ok_at"))
    if bal is None or ok_at is None:
        return False
    return (_now() - ok_at).total_seconds() <= STALE_AFTER_SECONDS


def available(wallet: Optional[dict]) -> float:
    """Spendable amount: balance minus the safety buffer, never below 0."""
    bal = _num((wallet or {}).get("balance")) or 0.0
    return max(round(bal - BUFFER_GHS, 2), 0.0)


def is_in_stock(price, wallet: Optional[dict] = None) -> bool:
    """Can the wallet cover a bundle selling at `price`?"""
    w = wallet if wallet is not None else get_wallet()
    if not gating_active(w):
        return True
    p = _num(price)
    if p is None:
        return True
    return p <= available(w) + 1e-9


def reference_prices() -> Dict[tuple, float]:
    """{(network_lower, bundle_lower): selling price} from the `prices` table."""
    now = time.time()
    with _lock:
        if _price_cache["map"] and now - _price_cache["ts"] < _PRICE_TTL:
            return _price_cache["map"]
    try:
        rows = _db().table("prices").select("network, bundle, price").execute().data or []
    except Exception as exc:
        logger.warning("DATAMART STOCK: couldn't read prices (%s)", exc)
        return {}
    mp = {}
    for r in rows:
        p = _num(r.get("price"))
        if p is not None:
            mp[(str(r.get("network", "")).strip().lower(), str(r.get("bundle", "")).strip().lower())] = p
    with _lock:
        _price_cache["map"] = mp
        _price_cache["ts"] = now
    return mp


def bundle_in_stock(network: str, bundle: str) -> bool:
    """Order-time guard. Unknown bundles pass; the caller's own lookup rejects them."""
    w = get_wallet()
    if not gating_active(w):
        return True
    price = reference_prices().get((str(network).strip().lower(), str(bundle).strip().lower()))
    return True if price is None else is_in_stock(price, w)


def annotate(rows: List[dict]) -> List[dict]:
    """Add `in_stock` to rows that carry network + bundle (any price shape)."""
    w = get_wallet()
    active = gating_active(w)
    prices = reference_prices() if active else {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        if not active:
            r["in_stock"] = True
            continue
        ref = prices.get((str(r.get("network", "")).strip().lower(), str(r.get("bundle", "")).strip().lower()))
        r["in_stock"] = True if ref is None else is_in_stock(ref, w)
    return rows


OUT_OF_STOCK_MESSAGE = "This bundle is temporarily out of stock. Please try a smaller bundle or check back soon."


# ============================================================================
# REFRESH (poller + admin button)
# ============================================================================

def refresh_balance(source: str = "poller") -> dict:
    """Read DataMart's balance, save it, log it if it changed. Never raises."""
    with _refresh_lock:
        now_iso = _now().isoformat()
        try:
            new_bal = fetch_remote_balance()
        except Exception as exc:
            logger.warning("DATAMART STOCK: balance check failed (%s)", exc)
            try:
                _db().table("datamart_wallet").upsert(
                    {"id": 1, "last_checked_at": now_iso, "last_error": str(exc)[:300]}
                ).execute()
            except Exception as db_exc:
                logger.error("DATAMART STOCK: couldn't record failure (%s)", db_exc)
            _clear_cache()
            return {"ok": False, "error": str(exc)[:300]}

        try:
            res = _db().table("datamart_wallet").select("*").eq("id", 1).limit(1).execute()
            prev_row = res.data[0] if res.data else None
        except Exception:
            prev_row = None
        prev_bal = _num((prev_row or {}).get("balance"))
        changed = prev_bal is None or abs(new_bal - prev_bal) >= 0.005

        row = {
            "id": 1,
            "balance": new_bal,
            "last_checked_at": now_iso,
            "last_ok_at": now_iso,
            "last_error": None,
        }
        if changed:
            row["previous_balance"] = prev_bal
            row["last_changed_at"] = now_iso
        try:
            _db().table("datamart_wallet").upsert(row).execute()
            if changed:
                _db().table("datamart_wallet_log").insert({
                    "balance": new_bal,
                    "previous_balance": prev_bal,
                    "delta": None if prev_bal is None else round(new_bal - prev_bal, 2),
                    "source": source,
                }).execute()
        except Exception as exc:
            logger.error("DATAMART STOCK: couldn't save balance (%s)", exc)
            _clear_cache()
            return {"ok": False, "error": f"save failed: {exc}"[:300]}

        if changed:
            logger.info("DATAMART STOCK: balance %s -> %s (%s)", prev_bal, new_bal, source)
            if new_bal < LOW_BALANCE_GHS and (prev_bal is None or prev_bal >= LOW_BALANCE_GHS):
                logger.warning("DATAMART STOCK: wallet is low (GHS %.2f) — some bundles will go out of stock", new_bal)
        _clear_cache()
        return {"ok": True, "balance": new_bal, "previous_balance": prev_bal, "changed": changed}


def _run_recheck(reason: str) -> None:
    with _recheck_lock:
        _recheck_state["timer"] = None
        _recheck_state["last"] = time.time()
    try:
        refresh_balance(source=reason)
    except Exception as exc:
        logger.error("DATAMART STOCK recheck error: %s", exc)


def schedule_recheck(reason: str = "purchase") -> None:
    """Re-read the wallet shortly after a purchase. Bursts of purchases are
    coalesced: at most one check per RECHECK_MIN_GAP seconds, never blocking the caller."""
    try:
        with _recheck_lock:
            if _recheck_state["timer"] is not None:
                return                      # a check is already queued; it will see this purchase too
            wait = _recheck_state["last"] + RECHECK_MIN_GAP - time.time()
            timer = threading.Timer(max(wait, RECHECK_SETTLE), _run_recheck, args=(reason,))
            timer.daemon = True
            _recheck_state["timer"] = timer
            timer.start()
    except Exception as exc:
        logger.warning("DATAMART STOCK: couldn't schedule recheck (%s)", exc)


def purchase_post(*args, **kwargs):
    """requests.post for any DataMart purchase call. Whatever the outcome
    (success or rejection) the wallet is re-read right after."""
    try:
        return requests.post(*args, **kwargs)
    finally:
        schedule_recheck("purchase")


async def poller_loop() -> None:
    """Started from core.startup_event. Survives any single failure."""
    await asyncio.sleep(20)
    while True:
        try:
            await asyncio.to_thread(refresh_balance, "poller")
        except Exception as exc:  # refresh_balance never raises; belt and braces
            logger.error("DATAMART STOCK poller error: %s", exc)
        await asyncio.sleep(POLL_SECONDS)


# ============================================================================
# ADMIN VIEW
# ============================================================================

def _capacity(bundle: str) -> float:
    digits = "".join(c if (c.isdigit() or c == ".") else " " for c in str(bundle)).split()
    try:
        return float(digits[0])
    except (IndexError, ValueError):
        return 1e9


def admin_status() -> dict:
    wallet = get_wallet(force=True)
    active = gating_active(wallet)
    avail = available(wallet)
    out: List[dict] = []
    total = 0
    for (net, bun), price in reference_prices().items():
        total += 1
        if active and price > avail + 1e-9:
            out.append({"network": net.upper(), "bundle": bun.upper(), "price": price})
    out.sort(key=lambda r: (r["network"], _capacity(r["bundle"])))
    try:
        log = _db().table("datamart_wallet_log").select("*").order("created_at", desc=True).limit(30).execute().data or []
    except Exception:
        log = []
    w = wallet or {}
    return {
        "configured": bool(os.getenv("DATAMART_API_KEY")),
        "balance": _num(w.get("balance")),
        "previous_balance": _num(w.get("previous_balance")),
        "available": avail if wallet else None,
        "buffer": BUFFER_GHS,
        "low_threshold": LOW_BALANCE_GHS,
        "low": bool(wallet) and (_num(w.get("balance")) or 0) < LOW_BALANCE_GHS,
        "last_checked_at": w.get("last_checked_at"),
        "last_ok_at": w.get("last_ok_at"),
        "last_changed_at": w.get("last_changed_at"),
        "last_error": w.get("last_error"),
        "gating_active": active,
        "poll_seconds": POLL_SECONDS,
        "bundles_total": total,
        "out_of_stock": out,
        "log": log,
    }
