"""
DashXera — internal admin operations dashboard for EVOS Data Services.

An admin layer on top of EVOSDATA. It reads the existing schema and reuses
main.py's own provider functions; it is not a second ordering engine.

Mounting (two lines at the bottom of main.py):

    import dashxera
    dashxera.install(app)


Three money concepts, kept strictly separate everywhere:

    orders.price        SOLD   — what the customer was charged. Revenue.
    orders.base_price   COST   — historical cost recorded on the order itself.
    orders.agent_price  AGENT  — what the agent's tier priced it at.

base_price is never back-filled from the current base_prices table into a
stored figure. Orders that carry no base_price are counted separately and
costed as an explicit estimate with its own coverage percentage, so an admin
can always see how much of a margin number is grounded in recorded history.

Aggregation runs as Postgres functions (see the v2 migration). If those
functions are missing the module falls back to paging rows in Python, so a
half-applied migration degrades rather than breaks.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import queue
import re
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from services.evosdata.admin_auth import AdminTokenInvalid, require_active_admin

logger = logging.getLogger("dashxera")

# ============================================================================
# CONFIG
# ============================================================================

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "")

ALLOWED_WINDOWS = (7, 14, 30, 60, 90)

PAYSTACK_LOW_BALANCE_GHS = float(os.getenv("PAYSTACK_LOW_BALANCE_GHS", "300"))

# A provider is flagged unhealthy when its failure rate crosses this.
PROVIDER_FAILURE_THRESHOLD = float(os.getenv("PROVIDER_FAILURE_THRESHOLD", "0.25"))

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

# evosgpt_purchases stores a tier, not an amount. Keep in sync with TIERS in
# the EvosGPT backend, or override with JSON.
EVOSGPT_TIER_PRICES = {"Pro": 20.0, "Core": 70.0, "Founder": 0.0}

# website_requests carries no amount column. These are estimates and are
# labelled as such everywhere they surface.
EVOSHUB_PACKAGE_PRICES = {"starter": 800.0, "business": 2000.0, "premium": 4500.0, "custom": 0.0}


def _json_env(name: str, default: dict) -> dict:
    raw = os.getenv(name)
    if not raw:
        return dict(default)
    try:
        return {str(k): float(v) for k, v in json.loads(raw).items()}
    except Exception:
        logger.warning("DASHXERA: %s is not valid JSON, using defaults", name)
        return dict(default)


EVOSGPT_TIER_PRICES = _json_env("EVOSGPT_TIER_PRICES", EVOSGPT_TIER_PRICES)
EVOSHUB_PACKAGE_PRICES = _json_env("EVOSHUB_PACKAGE_PRICES", EVOSHUB_PACKAGE_PRICES)

# Order status vocabulary exactly as main.py writes it.
STATUS_AWAITING = ("pending_payment",)
STATUS_IN_FLIGHT = ("paid", "processing")
STATUS_SUCCESS = ("successful",)
STATUS_FAILED = ("failed",)

PROVIDER_NAMES = ("DATAMART", "BUNDLES_GHANA", "SWIFT_DATA_LINK", "AGYEKUMDATA", "PAYSTACK", "MOOLRE")

# Agent wallet orders are debited directly and never touch a Paystack charge.
AGENT_REF_PREFIX = "EVOS-AGT-"


# ============================================================================
# LAZY BRIDGE INTO main.py
# main.py imports this module, so a module-level `import main` would be
# circular. Resolve at call time, by which point main is fully loaded.
# ============================================================================

_MAIN_MODULE_NAME = os.getenv("DASHXERA_MAIN_MODULE", "services.evosdata.core")


def _main():
    mod = sys.modules.get(_MAIN_MODULE_NAME)
    if mod is not None:
        return mod
    try:
        return importlib.import_module(_MAIN_MODULE_NAME)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(500, f"DashXera cannot reach the app module: {exc}")


def _from_main(name: str, default=None):
    try:
        return getattr(_main(), name, default)
    except Exception:
        return default


def _db():
    client = _from_main("supabase")
    if client is None:
        raise HTTPException(500, "Supabase client unavailable")
    return client


# ============================================================================
# HELPERS
# ============================================================================


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    for candidate in (text, text.split(".")[0]):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(value: Any) -> float:
    """
    Round money half-up, the way an accountant does.

    Python's built-in round() is banker's rounding: round(12.155, 2) gives
    12.15, not 12.16. Over a reporting period that quietly biases every
    average and margin downward, so currency never goes through round().
    """
    try:
        return float(Decimal(str(_num(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0


def _pct(part: Any, whole: Any) -> float:
    part, whole = _num(part), _num(whole)
    return _money(part / whole * 100) if whole else 0.0


def _window(days: Any) -> int:
    """Clamp to the supported reporting periods. 7 minimum, 90 maximum."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        return 7
    if days in ALLOWED_WINDOWS:
        return days
    if days < ALLOWED_WINDOWS[0]:
        return ALLOWED_WINDOWS[0]
    if days > ALLOWED_WINDOWS[-1]:
        return ALLOWED_WINDOWS[-1]
    return min(ALLOWED_WINDOWS, key=lambda d: (abs(d - days), d))


def _page_all(build, page_size: int = 1000, hard_cap: int = 60000) -> List[dict]:
    rows: List[dict] = []
    offset = 0
    while offset < hard_cap:
        batch = build().range(offset, offset + page_size - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def _rpc(name: str, params: dict) -> Optional[list]:
    """
    Call a Postgres aggregate. Returns None when the function isn't installed,
    so callers fall back to Python and a partially-applied migration degrades
    instead of 500ing.
    """
    try:
        result = _db().rpc(name, params).execute()
        return result.data if result.data is not None else []
    except Exception as exc:
        logger.info("DASHXERA: rpc %s unavailable (%s) — using Python fallback", name, exc)
        return None


# ============================================================================
# AUTH
# ============================================================================


def require_dashxera_admin(request: Request) -> str:
    """
    Gated by the same admin_agents roster as the rest of the Evoxera
    ecosystem (see admin_auth.py) rather than a single shared secret: the
    caller must present a bearer token from POST /admin/login, and that
    token's account must still have an active admin_agents row. Revoking
    that row takes effect on this admin's very next request, not just
    after their 12-hour token expires.

    The returned string is the audit-trail actor. It comes from
    admin_agents.display_name — the verified identity — never from a
    client-supplied header, so the audit log can't be spoofed by whoever
    happens to hold a session.
    """
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id, display_name = require_active_admin(_db(), token)
    except AdminTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access has been revoked.")
    return (display_name or "").strip() or f"admin-{user_id}"


router = APIRouter(prefix="/admin/dashxera", tags=["dashxera"])


# ============================================================================
# INCIDENTS
# ============================================================================

_BALANCE_PATTERNS = (
    "insufficient", "insufficent", "low balance", "balance is low", "balance too low",
    "wallet balance", "not enough", "no funds", "top up", "topup", "fund your",
    "inadequate balance",
)
_RATE_PATTERNS = ("rate limit", "too many requests", "429", "throttle")
_DOWN_PATTERNS = (
    "timeout", "timed out", "connection", "unreachable", "502", "503", "504",
    "bad gateway", "gateway timeout", "temporarily unavailable", "max retries exceeded",
)
_STOCK_PATTERNS = (
    "out of stock", "no active", "not available", "unavailable bundle", "inactive",
    "no bundle", "package not found",
)
_AUTH_PATTERNS = (
    "unauthorized", "unauthorised", "401", "403", "invalid api key", "invalid credentials",
    "forbidden", "signature",
)

_INCIDENT_SEVERITY = {
    "low_balance": "critical",
    "auth": "critical",
    "provider_down": "warning",
    "rate_limited": "warning",
    "out_of_stock": "warning",
    "purchase_failed": "warning",
    "reprocess_failed": "warning",
    "payment": "warning",
}

INCIDENT_KINDS = tuple(_INCIDENT_SEVERITY.keys())


def classify_provider_error(message: str) -> str:
    text = (message or "").lower()
    if any(p in text for p in _BALANCE_PATTERNS):
        return "low_balance"
    if any(p in text for p in _RATE_PATTERNS):
        return "rate_limited"
    if any(p in text for p in _AUTH_PATTERNS):
        return "auth"
    if any(p in text for p in _DOWN_PATTERNS):
        return "provider_down"
    if any(p in text for p in _STOCK_PATTERNS):
        return "out_of_stock"
    return "purchase_failed"


def detect_provider(message: str, fallback: str = "UNKNOWN") -> str:
    text = (message or "").upper()
    for name in PROVIDER_NAMES:
        if name in text:
            return name
    if "BUNDLES GHANA" in text or "BG ORDER" in text:
        return "BUNDLES_GHANA"
    if "SDL" in text:
        return "SWIFT_DATA_LINK"
    return fallback


_DIGITS = re.compile(r"\d+")


def _fingerprint(provider: str, kind: str, message: str) -> str:
    # Strip numbers so "order 8813 failed" and "order 8814 failed" collapse
    # into one incident rather than two hundred.
    skeleton = _DIGITS.sub("#", (message or "").lower())[:300]
    return hashlib.sha256(f"{provider}|{kind}|{skeleton}".encode()).hexdigest()[:40]


_INCIDENT_QUEUE: "queue.Queue[dict]" = queue.Queue(maxsize=2000)
_worker_started = False
_worker_lock = threading.Lock()


def record_provider_incident(
    provider: str,
    message: str,
    *,
    kind: Optional[str] = None,
    order_id: Optional[int] = None,
    reference: Optional[str] = None,
    network: Optional[str] = None,
    bundle: Optional[str] = None,
) -> None:
    """Persist a provider failure. Never raises, never blocks a purchase."""
    try:
        kind = kind or classify_provider_error(message)
        _INCIDENT_QUEUE.put_nowait(
            {
                "provider": (provider or "UNKNOWN").upper()[:40],
                "kind": kind,
                "severity": _INCIDENT_SEVERITY.get(kind, "warning"),
                "message": (message or "")[:1000],
                "fingerprint": _fingerprint(provider, kind, message),
                "order_id": order_id,
                "reference": reference,
                "network": network,
                "bundle": bundle,
            }
        )
    except Exception:
        pass


def _persist_incident(item: dict) -> None:
    db = _from_main("supabase")
    if db is None:
        return
    now = utc_now().isoformat()

    existing = (
        db.table("provider_incidents")
        .select("id, occurrences")
        .eq("fingerprint", item["fingerprint"])
        .is_("resolved_at", None)
        .limit(1)
        .execute()
    )

    if existing.data:
        row = existing.data[0]
        db.table("provider_incidents").update(
            {
                "occurrences": int(row.get("occurrences") or 1) + 1,
                "last_seen_at": now,
                "message": item["message"],
                "order_id": item.get("order_id") or None,
                "reference": item.get("reference") or None,
            }
        ).eq("id", row["id"]).execute()
        return

    db.table("provider_incidents").insert(
        {**item, "first_seen_at": now, "last_seen_at": now, "occurrences": 1}
    ).execute()


def _incident_worker() -> None:
    while True:
        item = _INCIDENT_QUEUE.get()
        try:
            _persist_incident(item)
        except Exception as exc:
            logging.getLogger("dashxera.worker").debug("incident write failed: %s", exc)
        finally:
            _INCIDENT_QUEUE.task_done()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_incident_worker, name="dashxera-incidents", daemon=True).start()
        _worker_started = True


# ----------------------------------------------------------------------------
# LOG CAPTURE
#
# main.py already logs every provider rejection; those lines were just
# transient. This handler reads the same stream and persists them.
#
# Capture begins the moment install() runs. Server logs written before the
# integration existed are NOT recoverable — DashXera shows what it has
# persisted since, and nothing older.
# ----------------------------------------------------------------------------

_WATCHED_PHRASES = (
    "PURCHASE ERROR", "RETRY JOB", "ORDER PAYMENT RETRY", "STATUS SYNC",
    "BG ORDER FAILED", "SDL ORDER FAILED", "AGYEKUMDATA ORDER FAILED",
    "BUNDLES GHANA FETCH FAILED", "TRANSFER COULD NOT BE INITIATED",
    "WITHDRAWAL", "DEPOSIT RETRY", "PAYSTACK",
)

_ORDER_ID_RE = re.compile(r"order[ _]?(?:id[ =:]*)?(\d{1,12})", re.I)
_REF_RE = re.compile(r"\b((?:EVOS|DM|BG|SDL|AGD)[-_][A-Za-z0-9\-_]{4,40})\b")


class DashXeraLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name.startswith("dashxera"):
                return
            if record.levelno < logging.WARNING:
                return

            message = record.getMessage()
            upper = message.upper()
            if not any(phrase in upper for phrase in _WATCHED_PHRASES):
                return

            kind = classify_provider_error(message)
            # Routine retry chatter isn't an incident unless the underlying
            # reason is something an admin can act on.
            if kind == "purchase_failed" and record.levelno < logging.ERROR:
                return

            order_match = _ORDER_ID_RE.search(message)
            ref_match = _REF_RE.search(message)

            record_provider_incident(
                detect_provider(message, "UNKNOWN"),
                message,
                kind=kind,
                order_id=int(order_match.group(1)) if order_match else None,
                reference=ref_match.group(1) if ref_match else None,
            )
        except Exception:
            pass


def install_log_capture(target_logger: Optional[logging.Logger] = None) -> None:
    _ensure_worker()
    target = target_logger or logging.getLogger()
    if any(isinstance(h, DashXeraLogHandler) for h in target.handlers):
        return
    handler = DashXeraLogHandler()
    handler.setLevel(logging.WARNING)
    target.addHandler(handler)
    logger.info("DASHXERA: log capture installed on %s", target.name or "root")


# ============================================================================
# FINANCIALS
# ============================================================================


def _base_price_lookup() -> Dict[str, float]:
    """
    Current cost list. Used ONLY to estimate cost for orders that never
    recorded one — never to overwrite a recorded historical base_price.
    """
    try:
        rows = _db().table("base_prices").select("network, bundle, cost_price").execute().data or []
    except Exception:
        return {}
    return {
        f"{str(r.get('network','')).strip().lower()}::{str(r.get('bundle','')).strip().lower()}":
            _num(r.get("cost_price"))
        for r in rows
    }


def _order_cost(order: dict, lookup: Dict[str, float]) -> tuple:
    """
    Returns (cost, source). source is one of:
      recorded  — base_price stored on the order, historically accurate
      estimated — today's base_prices value; the order predates cost capture
      missing   — no cost known at all
    """
    if order.get("base_price") is not None:
        return _num(order["base_price"]), "recorded"
    key = f"{str(order.get('network','')).strip().lower()}::{str(order.get('bundle','')).strip().lower()}"
    if key in lookup:
        return lookup[key], "estimated"
    return 0.0, "missing"


def _summary_via_python(since_iso: str) -> dict:
    """Fallback when the aggregate functions aren't installed."""
    columns = "id, created_at, status, price, base_price, agent_price, network, bundle, agent_id, datamart_ref"
    orders = _page_all(lambda: _db().table("orders").select(columns).gte("created_at", since_iso))

    agg: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)

    for order in orders:
        status = str(order.get("status") or "").lower()
        price = _num(order.get("price"))
        counts["total_orders"] += 1

        if status in STATUS_AWAITING:
            counts["awaiting_payment"] += 1
        elif status in STATUS_IN_FLIGHT:
            counts["processing_orders"] += 1
        elif status in STATUS_SUCCESS:
            counts["successful_orders"] += 1
        elif status in STATUS_FAILED:
            counts["failed_orders"] += 1
        else:
            counts["other_orders"] += 1

        if status in STATUS_FAILED:
            agg["failed_value"] += price

        if status in STATUS_AWAITING:
            continue

        counts["paid_orders"] += 1
        agg["sold"] += price

        if order.get("base_price") is not None:
            agg["base_cost"] += _num(order["base_price"])
            counts["orders_with_base"] += 1
        else:
            counts["orders_missing_base"] += 1
            agg["sold_missing_base"] += price

        if not order.get("datamart_ref") and status not in STATUS_SUCCESS:
            counts["undispatched_orders"] += 1
            agg["undispatched_value"] += price

        if order.get("agent_id"):
            counts["agent_orders"] += 1
            agg["agent_sold"] += price
            agg["agent_price_total"] += _num(order.get("agent_price"))
        else:
            counts["direct_orders"] += 1
            agg["direct_sold"] += price

    return {**{k: int(v) for k, v in counts.items()}, **{k: float(v) for k, v in agg.items()}}


def _summary_row(since_iso: str) -> dict:
    rows = _rpc("dashxera_order_summary", {"since_ts": since_iso})
    if rows is None:
        return _summary_via_python(since_iso)
    return rows[0] if rows else {}


def _series(since: datetime) -> List[dict]:
    rows = _rpc("dashxera_daily_series", {"since_ts": since.isoformat()})

    if rows is None:
        orders = _page_all(
            lambda: _db().table("orders")
            .select("created_at, status, price, base_price")
            .gte("created_at", since.isoformat())
        )
        buckets: Dict[str, dict] = defaultdict(
            lambda: {"orders": 0, "sold": 0.0, "base_cost": 0.0, "failed": 0}
        )
        for order in orders:
            day = (_parse_dt(order.get("created_at")) or since).date().isoformat()
            status = str(order.get("status") or "").lower()
            if status in STATUS_FAILED:
                buckets[day]["failed"] += 1
            if status in STATUS_AWAITING:
                continue
            buckets[day]["orders"] += 1
            buckets[day]["sold"] += _num(order.get("price"))
            if order.get("base_price") is not None:
                buckets[day]["base_cost"] += _num(order["base_price"])
    else:
        buckets = {
            str(r["day"]): {
                "orders": int(r.get("orders") or 0),
                "sold": _num(r.get("sold")),
                "base_cost": _num(r.get("base_cost")),
                "failed": int(r.get("failed") or 0),
            }
            for r in rows
        }

    out = []
    cursor, today = since.date(), utc_now().date()
    while cursor <= today:
        key = cursor.isoformat()
        point = buckets.get(key) or {"orders": 0, "sold": 0.0, "base_cost": 0.0, "failed": 0}
        out.append({
            "date": key,
            "orders": point["orders"],
            "sold": _money(point["sold"]),
            "base_cost": _money(point["base_cost"]),
            "failed": point["failed"],
        })
        cursor += timedelta(days=1)
    return out


def _estimated_cost_for_gap(since_iso: str) -> float:
    """
    Cost estimate for orders with no recorded base_price, priced at today's
    cost list. Reported in its own field — never merged into recorded cost.
    """
    lookup = _base_price_lookup()
    if not lookup:
        return 0.0
    orders = _page_all(
        lambda: _db().table("orders")
        .select("network, bundle, status, base_price")
        .is_("base_price", None)
        .gte("created_at", since_iso)
    )
    total = 0.0
    for order in orders:
        if str(order.get("status") or "").lower() in STATUS_AWAITING:
            continue
        cost, source = _order_cost(order, lookup)
        if source == "estimated":
            total += cost
    return total


# ============================================================================
# ECOSYSTEM SALES
# ============================================================================


def _why(exc: Exception) -> str:
    text = str(exc)
    if "does not exist" in text or "PGRST" in text or "42P01" in text:
        return "Table not present in this project"
    return text[:160]


def _evosgpt_sales(since_iso: str) -> dict:
    try:
        rows = _page_all(
            lambda: _db().table("evosgpt_purchases")
            .select("id, tier, status, created_at").gte("created_at", since_iso)
        )
    except Exception as exc:
        return {"available": False, "reason": _why(exc), "revenue": 0.0, "count": 0,
                "status_label": "Not connected"}

    paid = [r for r in rows if str(r.get("status", "")).lower() in ("paid", "success", "successful")]
    by_tier: Dict[str, int] = defaultdict(int)
    for row in paid:
        by_tier[str(row.get("tier") or "unknown")] += 1

    return {
        "available": True,
        "estimated": True,  # price derives from the tier map, not a stored amount
        "estimate_reason": "evosgpt_purchases stores a tier, not an amount",
        "revenue": _money(sum(EVOSGPT_TIER_PRICES.get(str(r.get("tier")), 0.0) for r in paid)),
        "count": len(paid),
        "pending": len(rows) - len(paid),
        "breakdown": [{"label": k, "count": v} for k, v in sorted(by_tier.items())],
    }


def _evoshub_sales(since_iso: str) -> dict:
    try:
        rows = _page_all(
            lambda: _db().table("website_requests")
            .select("id, package, status, created_at").gte("created_at", since_iso)
        )
    except Exception as exc:
        return {"available": False, "reason": _why(exc), "revenue": 0.0, "count": 0,
                "status_label": "Not connected"}

    won = [r for r in rows if str(r.get("status", "")).lower() == "closed"]
    by_package: Dict[str, int] = defaultdict(int)
    for row in won:
        by_package[str(row.get("package") or "unknown")] += 1

    return {
        "available": True,
        "estimated": True,
        "estimate_reason": "website_requests has no amount column",
        "revenue": _money(sum(EVOSHUB_PACKAGE_PRICES.get(str(r.get("package", "")).lower(), 0.0) for r in won)),
        "count": len(won),
        "pending": len(rows) - len(won),
        "breakdown": [{"label": k, "count": v} for k, v in sorted(by_package.items())],
    }


def _xera_sales(since_iso: str) -> dict:
    """
    XERA lives in the hub schema and may not be reachable from this project.
    When it isn't, the card reads "Not connected" — never fabricated revenue.
    """
    try:
        rows = _page_all(
            lambda: _db().table("xera_purchases")
            .select("id, price_ghs, xera_amount, status, created_at").gte("created_at", since_iso)
        )
    except Exception as exc:
        return {"available": False, "reason": _why(exc), "revenue": 0.0, "count": 0,
                "status_label": "Not connected"}

    paid = [r for r in rows
            if str(r.get("status", "")).lower() in ("paid", "success", "successful", "completed")]
    return {
        "available": True,
        "estimated": False,
        "revenue": _money(sum(_num(r.get("price_ghs")) for r in paid)),
        "count": len(paid),
        "pending": len(rows) - len(paid),
        "tokens_sold": _money(sum(_num(r.get("xera_amount")) for r in paid)),
        "breakdown": [],
    }


# ============================================================================
# OVERVIEW
# ============================================================================


@router.get("/summary")
def dashxera_summary(days: int = Query(7), _: str = Depends(require_dashxera_admin)):
    days = _window(days)
    since = utc_now() - timedelta(days=days)
    since_iso = since.isoformat()

    row = _summary_row(since_iso)

    total = int(row.get("total_orders") or 0)
    successful = int(row.get("successful_orders") or 0)
    failed = int(row.get("failed_orders") or 0)
    paid_orders = int(row.get("paid_orders") or 0)

    sold = _num(row.get("sold"))
    recorded_cost = _num(row.get("base_cost"))
    with_base = int(row.get("orders_with_base") or 0)
    missing_base = int(row.get("orders_missing_base") or 0)

    # Cost for the gap is estimated from today's list and kept in its own
    # field. recorded_margin is the figure grounded entirely in history.
    estimated_cost = _estimated_cost_for_gap(since_iso) if missing_base else 0.0
    sold_with_base = sold - _num(row.get("sold_missing_base"))
    settled = successful + failed

    return {
        "status": True,
        "window_days": days,
        "since": since_iso,
        "generated_at": utc_now().isoformat(),

        "orders": {
            "total": total,
            "successful": successful,
            "processing": int(row.get("processing_orders") or 0),
            "failed": failed,
            "awaiting_payment": int(row.get("awaiting_payment") or 0),
            "other": int(row.get("other_orders") or 0),
            "paid": paid_orders,
            "undispatched": int(row.get("undispatched_orders") or 0),
        },

        # Three separate concepts. Never collapsed into one another.
        "financials": {
            "total_sold": _money(sold),
            "recorded_base_cost": _money(recorded_cost),
            "estimated_base_cost": _money(estimated_cost),
            "total_base_cost": _money(recorded_cost + estimated_cost),

            "recorded_margin": _money(sold_with_base - recorded_cost),
            "gross_margin": _money(sold - recorded_cost - estimated_cost),
            "margin_pct": _pct(sold - recorded_cost - estimated_cost, sold),

            "average_sold": _money(sold / paid_orders) if paid_orders else 0.0,
            "average_base_cost": _money(recorded_cost / with_base) if with_base else 0.0,

            "paid_orders": paid_orders,
            "agent_sold": _money(row.get("agent_sold")),
            "agent_price_total": _money(row.get("agent_price_total")),
            "agent_orders": int(row.get("agent_orders") or 0),
            "direct_sold": _money(row.get("direct_sold")),
            "direct_orders": int(row.get("direct_orders") or 0),

            "failed_value": _money(row.get("failed_value")),
            "undispatched_value": _money(row.get("undispatched_value")),

            "cost_coverage": {
                "orders_with_recorded_cost": with_base,
                "orders_without_recorded_cost": missing_base,
                "coverage_pct": _pct(with_base, with_base + missing_base),
                "note": (
                    "Orders without a recorded base_price are costed at today's "
                    "base_prices list. That estimate is shown separately and is "
                    "not historical."
                ) if missing_base else "Every paid order carries its own historical cost.",
            },
        },

        "quality": {
            "success_rate": _pct(successful, settled),
            "failure_rate": _pct(failed, settled),
            "settled": settled,
        },

        "series": _series(since),
    }


@router.get("/ecosystem")
def dashxera_ecosystem(days: int = Query(7), _: str = Depends(require_dashxera_admin)):
    days = _window(days)
    since_iso = (utc_now() - timedelta(days=days)).isoformat()

    row = _summary_row(since_iso)
    products = {
        "evosdata": {
            "available": True,
            "estimated": False,
            "revenue": _money(row.get("sold")),
            "count": int(row.get("paid_orders") or 0),
            "pending": int(row.get("awaiting_payment") or 0),
            "breakdown": [],
        },
        "evosgpt": _evosgpt_sales(since_iso),
        "evoshub": _evoshub_sales(since_iso),
        "xera": _xera_sales(since_iso),
    }

    connected = [p for p in products.values() if p.get("available")]
    return {
        "status": True,
        "window_days": days,
        "products": products,
        "total_revenue": _money(sum(_num(p.get("revenue")) for p in connected)),
        "includes_estimates": any(p.get("estimated") for p in connected),
    }


# ============================================================================
# ORDERS
# ============================================================================


def _agent_names(agent_ids) -> Dict[Any, str]:
    """agent_id references users(id) — there is no separate agents table."""
    ids = [i for i in agent_ids if i]
    if not ids:
        return {}
    try:
        rows = (
            _db().table("users")
            .select("id, username, full_name, store_name")
            .in_("id", ids).execute().data or []
        )
    except Exception:
        return {}
    return {
        r["id"]: (r.get("store_name") or r.get("full_name") or r.get("username") or f"Agent {r['id']}")
        for r in rows
    }


def _infer_provider(order: dict) -> Optional[str]:
    """
    Historical orders never recorded which provider handled them — only a
    provider_priority tier. Reconstruct from the network's current chain.
    Callers surface this as inferred, never as fact.
    """
    chain_fn = _from_main("get_provider_chain")
    if not chain_fn or not order.get("network"):
        return None
    try:
        chain = chain_fn(order["network"]) or []
    except Exception:
        return None
    if not chain:
        return None
    index = min(max(int(order.get("provider_priority") or 1) - 1, 0), len(chain) - 1)
    return chain[index]


ORDER_COLUMNS = (
    "id, created_at, status, price, base_price, agent_price, network, bundle, "
    "phone_number, email, guest_email, user_id, agent_id, paystack_ref, "
    "evosdata_ref, datamart_ref, datamart_order_id, dispatch_provider, "
    "provider_priority, retry_attempts, reprocess_count, reprocessed_at, last_error"
)


def _decorate_orders(rows: List[dict]) -> None:
    lookup = _base_price_lookup()
    names = _agent_names({r.get("agent_id") for r in rows})
    for row in rows:
        cost, source = _order_cost(row, lookup)
        row["base_cost"] = _money(cost)
        row["base_cost_source"] = source
        row["margin"] = _money(_num(row.get("price")) - cost) if source != "missing" else None
        row["agent_name"] = names.get(row.get("agent_id"))
        row["sale_type"] = "agent" if row.get("agent_id") else "direct"
        row["customer"] = row.get("email") or row.get("guest_email") or row.get("phone_number")
        row["provider"] = row.get("dispatch_provider") or _infer_provider(row)
        row["provider_recorded"] = bool(row.get("dispatch_provider"))


@router.get("/orders")
def dashxera_orders(
    days: int = Query(7),
    status: Optional[str] = Query(None, max_length=30),
    agent_id: Optional[int] = Query(None, ge=1),
    network: Optional[str] = Query(None, max_length=20),
    search: Optional[str] = Query(None, max_length=80),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    _: str = Depends(require_dashxera_admin),
):
    days = _window(days)
    since_iso = (utc_now() - timedelta(days=days)).isoformat()
    offset = (page - 1) * page_size

    query = _db().table("orders").select(ORDER_COLUMNS, count="exact").gte("created_at", since_iso)
    if status:
        query = query.eq("status", re.sub(r"[^a-z_]", "", status.lower()))
    if agent_id:
        query = query.eq("agent_id", agent_id)
    if network:
        query = query.eq("network", re.sub(r"[^A-Z]", "", network.upper()))
    if search:
        # Strip PostgREST filter metacharacters before they reach the or_()
        # grammar. Values are still sent as parameters, never concatenated SQL.
        safe = re.sub(r"[%,()\"'\\]", "", search.strip())
        if safe:
            query = query.or_(
                f"paystack_ref.ilike.%{safe}%,evosdata_ref.ilike.%{safe}%,"
                f"datamart_ref.ilike.%{safe}%,phone_number.ilike.%{safe}%"
            )

    result = query.order("created_at", desc=True).range(offset, offset + page_size - 1).execute()
    rows = result.data or []
    total = getattr(result, "count", None)
    _decorate_orders(rows)

    return {
        "status": True, "window_days": days, "page": page, "page_size": page_size,
        "total": total,
        "has_more": bool(total is not None and offset + len(rows) < total),
        "orders": rows,
    }


# ============================================================================
# AGENTS
# ============================================================================


@router.get("/agents")
def dashxera_agents(days: int = Query(7), _: str = Depends(require_dashxera_admin)):
    days = _window(days)
    since_iso = (utc_now() - timedelta(days=days)).isoformat()

    rows = _rpc("dashxera_agent_summary", {"since_ts": since_iso})

    if rows is None:
        orders = _page_all(
            lambda: _db().table("orders")
            .select("agent_id, price, agent_price, base_price, status")
            .not_.is_("agent_id", None)
            .gte("created_at", since_iso)
        )
        grouped: Dict[Any, dict] = defaultdict(
            lambda: {"orders": 0, "sold": 0.0, "agent_price_total": 0.0, "base_cost": 0.0,
                     "orders_with_base": 0, "successful_orders": 0, "failed_orders": 0}
        )
        for order in orders:
            status = str(order.get("status") or "").lower()
            if status in STATUS_AWAITING:
                continue
            bucket = grouped[order["agent_id"]]
            bucket["orders"] += 1
            bucket["sold"] += _num(order.get("price"))
            bucket["agent_price_total"] += _num(order.get("agent_price"))
            if order.get("base_price") is not None:
                bucket["base_cost"] += _num(order["base_price"])
                bucket["orders_with_base"] += 1
            if status in STATUS_SUCCESS:
                bucket["successful_orders"] += 1
            elif status in STATUS_FAILED:
                bucket["failed_orders"] += 1

        names = _agent_names(set(grouped.keys()))
        rows = [
            {"agent_id": aid, "agent_name": names.get(aid, f"Agent {aid}"),
             "agent_username": None, **data}
            for aid, data in grouped.items()
        ]
        rows.sort(key=lambda r: -_num(r.get("sold")))

    agents = []
    for row in rows:
        sold = _num(row.get("sold"))
        recorded_cost = _num(row.get("base_cost"))
        order_count = int(row.get("orders") or 0)
        agents.append({
            "agent_id": row.get("agent_id"),
            "agent_name": row.get("agent_name") or f"Agent {row.get('agent_id')}",
            "agent_username": row.get("agent_username"),
            "orders": order_count,
            "sold": _money(sold),
            "agent_price_total": _money(row.get("agent_price_total")),
            "recorded_base_cost": _money(recorded_cost),
            "cost_coverage_pct": _pct(int(row.get("orders_with_base") or 0), order_count),
            "margin_vs_recorded_cost": _money(sold - recorded_cost),
            "successful_orders": int(row.get("successful_orders") or 0),
            "failed_orders": int(row.get("failed_orders") or 0),
        })

    return {
        "status": True,
        "window_days": days,
        "agent_count": len(agents),
        "total_agent_sold": _money(sum(a["sold"] for a in agents)),
        "total_agent_price": _money(sum(a["agent_price_total"] for a in agents)),
        "agents": agents,
        "note": "Orders with no agent_id are direct sales and are excluded here.",
    }


# ============================================================================
# PROVIDER + PAYMENT HEALTH
# ============================================================================


def _paystack_balance() -> dict:
    """
    Paystack documents GET /balance, so this figure is real. It is the only
    balance endpoint DashXera calls anywhere.
    """
    if not PAYSTACK_SECRET:
        return {"provider": "PAYSTACK", "balance_available": False,
                "reason": "No Paystack secret configured"}
    try:
        res = requests.get(
            "https://api.paystack.co/balance",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"}, timeout=8,
        )
        payload = res.json()
        if not payload.get("status"):
            return {"provider": "PAYSTACK", "balance_available": False,
                    "reason": payload.get("message", "Balance check failed")}

        entries = payload.get("data") or []
        ghs = next((e for e in entries if str(e.get("currency")).upper() == "GHS"),
                   entries[0] if entries else None)
        if not ghs:
            return {"provider": "PAYSTACK", "balance_available": False, "reason": "No balance returned"}

        amount = _num(ghs.get("balance")) / 100.0  # Paystack reports pesewas
        return {
            "provider": "PAYSTACK", "balance_available": True, "balance": _money(amount),
            "currency": str(ghs.get("currency", "GHS")).upper(),
            "threshold": PAYSTACK_LOW_BALANCE_GHS,
            "low": amount < PAYSTACK_LOW_BALANCE_GHS,
            "note": "Funds available for agent withdrawal transfers",
        }
    except Exception as exc:
        return {"provider": "PAYSTACK", "balance_available": False, "reason": str(exc)[:160]}


def _configured_providers() -> List[str]:
    """The providers actually routed to, read from provider_routes."""
    try:
        rows = _db().table("provider_routes").select("provider, active").execute().data or []
    except Exception:
        return list(PROVIDER_NAMES[:4])
    active = sorted({r["provider"] for r in rows if r.get("provider") and r.get("active")})
    return active or list(PROVIDER_NAMES[:4])


@router.get("/providers")
def dashxera_providers(days: int = Query(7), _: str = Depends(require_dashxera_admin)):
    """
    Provider health derived from real signals only: dispatch outcomes recorded
    on orders, plus persisted incidents.

    No provider balance is reported except Paystack's, which is a documented
    endpoint. DataMart, Bundles Ghana, Swift Data Link and Agyekumdata expose
    no balance API in this integration, so their low-balance signal comes from
    the rejection text itself, captured as a low_balance incident.
    """
    days = _window(days)
    since_iso = (utc_now() - timedelta(days=days)).isoformat()

    activity = {}
    rows = _rpc("dashxera_provider_activity", {"since_ts": since_iso})
    if rows:
        activity = {str(r["provider"]): r for r in rows}

    try:
        incidents = (
            _db().table("provider_incidents")
            .select("id, provider, kind, severity, message, occurrences, last_seen_at, order_id")
            .gte("last_seen_at", since_iso).is_("resolved_at", None)
            .order("last_seen_at", desc=True).limit(300).execute().data or []
        )
    except Exception as exc:
        incidents = []
        logger.warning("DASHXERA: incident read failed: %s", exc)

    by_provider: Dict[str, list] = defaultdict(list)
    for inc in incidents:
        by_provider[str(inc.get("provider"))].append(inc)

    providers = []
    for name in _configured_providers():
        stats = activity.get(name, {})
        orders = int(stats.get("orders") or 0)
        failed = int(stats.get("failed_orders") or 0)
        own = by_provider.get(name, [])
        low_balance = [i for i in own if i.get("kind") == "low_balance"]
        failure_rate = (failed / orders) if orders else 0.0

        if low_balance:
            health = "LOW"
        elif any(i.get("severity") == "critical" for i in own):
            health = "ERROR"
        elif orders and failure_rate >= PROVIDER_FAILURE_THRESHOLD:
            health = "ERROR"
        elif own:
            health = "DEGRADED"
        elif orders:
            health = "HEALTHY"
        else:
            health = "IDLE"

        providers.append({
            "provider": name,
            "health": health,
            "balance_available": False,
            "balance_note": "No balance endpoint in this integration — low balance is detected from rejection messages",
            "low_balance_incidents": len(low_balance),
            "latest_low_balance": low_balance[0]["message"] if low_balance else None,
            "orders": orders,
            "successful_orders": int(stats.get("successful_orders") or 0),
            "failed_orders": failed,
            "failure_rate_pct": _pct(failed, orders),
            "last_success_at": stats.get("last_success_at"),
            "open_incidents": len(own),
            "recent_failures": own[:3],
        })

    paystack = _paystack_balance()
    pay_incidents = by_provider.get("PAYSTACK", [])
    paystack.update({
        "health": (
            "LOW" if paystack.get("low")
            else "ERROR" if any(i.get("severity") == "critical" for i in pay_incidents)
            else "DEGRADED" if pay_incidents
            else "HEALTHY" if paystack.get("balance_available")
            else "UNKNOWN"
        ),
        "open_incidents": len(pay_incidents),
        "recent_failures": pay_incidents[:3],
    })

    unrecorded = activity.get("UNRECORDED", {})
    attention = [p for p in providers if p["health"] in ("LOW", "ERROR")]
    if paystack["health"] in ("LOW", "ERROR"):
        attention.append(paystack)

    return {
        "status": True,
        "window_days": days,
        "providers": providers,
        "paystack": paystack,
        "attention": attention,
        "unattributed_orders": int(unrecorded.get("orders") or 0),
        "unattributed_note": (
            "Orders placed before dispatch_provider was recorded cannot be "
            "attributed to a provider. New dispatches are attributed."
        ),
    }


# ============================================================================
# INCIDENTS
# ============================================================================


@router.get("/incidents")
def dashxera_incidents(
    days: int = Query(7),
    include_resolved: bool = Query(False),
    kind: Optional[str] = Query(None, max_length=30),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    _: str = Depends(require_dashxera_admin),
):
    days = _window(days)
    since_iso = (utc_now() - timedelta(days=days)).isoformat()
    offset = (page - 1) * page_size

    if kind and kind not in INCIDENT_KINDS:
        raise HTTPException(400, f"Unknown incident kind: {kind}")

    try:
        query = (_db().table("provider_incidents").select("*", count="exact")
                 .gte("last_seen_at", since_iso))
        if not include_resolved:
            query = query.is_("resolved_at", None)
        if kind:
            query = query.eq("kind", kind)
        result = (query.order("last_seen_at", desc=True)
                  .range(offset, offset + page_size - 1).execute())
        incidents = result.data or []
        total = getattr(result, "count", None)
    except Exception as exc:
        logger.warning("DASHXERA: incident read failed: %s", exc)
        return {"status": True, "window_days": days, "incidents": [], "total": 0,
                "counts": {"open": 0, "critical": 0, "by_kind": {}},
                "note": "Incident table unavailable — run the DashXera migration"}

    by_kind: Dict[str, int] = defaultdict(int)
    for row in incidents:
        by_kind[str(row.get("kind"))] += int(row.get("occurrences") or 1)

    return {
        "status": True, "window_days": days, "page": page, "page_size": page_size,
        "total": total, "incidents": incidents,
        "counts": {
            "open": len([r for r in incidents if not r.get("resolved_at")]),
            "critical": len([r for r in incidents if r.get("severity") == "critical"]),
            "by_kind": dict(by_kind),
        },
        "capture_note": (
            "Incidents are persisted from the moment DashXera was installed. "
            "Server logs written before then are not recoverable."
        ),
    }


class ResolveRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


@router.post("/incidents/{incident_id}/resolve")
def dashxera_resolve_incident(
    incident_id: int,
    payload: Optional[ResolveRequest] = None,
    actor: str = Depends(require_dashxera_admin),
):
    try:
        _db().table("provider_incidents").update({
            "resolved_at": utc_now().isoformat(),
            "resolved_by": actor,
            "note": payload.note if payload else None,
        }).eq("id", incident_id).execute()
    except Exception as exc:
        raise HTTPException(500, f"Could not resolve incident: {exc}")

    _audit("resolve_incident", outcome="success", detail=f"incident {incident_id}", actor=actor)
    return {"status": True, "resolved": incident_id}


@router.get("/alerts")
def dashxera_alerts_legacy(days: int = Query(7), actor: str = Depends(require_dashxera_admin)):
    """Kept so a v1 frontend still deployed doesn't 404 mid-rollout."""
    return dashxera_incidents(days=days, include_resolved=False, kind=None,
                              page=1, page_size=DEFAULT_PAGE_SIZE, _=actor)


# ============================================================================
# PAID BUT NOT DISPATCHED
# ============================================================================


def _is_eligible(order: dict) -> tuple:
    """
    Single source of truth for reprocess eligibility. Used by the listing, the
    single reprocess and the bulk path, so the three can never disagree.
    """
    status = str(order.get("status") or "").lower()

    if order.get("datamart_ref"):
        return False, f"Already dispatched ({order['datamart_ref']})"
    if status in STATUS_SUCCESS:
        return False, "Order already fulfilled"
    if status in STATUS_AWAITING:
        return False, "Customer never completed payment"
    if status not in STATUS_IN_FLIGHT + STATUS_FAILED:
        return False, f"Status {status or 'unknown'} is not reprocessable"
    if not (order.get("paystack_ref") or order.get("evosdata_ref")):
        return False, "No payment reference on the order"
    return True, "Paid, no provider reference"


@router.get("/undispatched")
def dashxera_undispatched(
    days: int = Query(7),
    verify: bool = Query(False, description="Ask Paystack about each reference (max 25)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    _: str = Depends(require_dashxera_admin),
):
    days = _window(days)
    since_iso = (utc_now() - timedelta(days=days)).isoformat()
    offset = (page - 1) * page_size

    result = (
        _db().table("orders").select(ORDER_COLUMNS, count="exact")
        .is_("datamart_ref", None)
        .gte("created_at", since_iso)
        .in_("status", list(STATUS_IN_FLIGHT + STATUS_FAILED + STATUS_AWAITING))
        .order("created_at", desc=True)
        .range(offset, offset + page_size - 1).execute()
    )
    rows = result.data or []
    total = getattr(result, "count", None)
    _decorate_orders(rows)

    for row in rows:
        ref = str(row.get("paystack_ref") or "")
        eligible, reason = _is_eligible(row)
        row["wallet_order"] = ref.startswith(AGENT_REF_PREFIX)
        row["eligible"] = eligible
        row["eligibility_reason"] = reason
        row["provider_attempted"] = row.get("provider")
        row["age_hours"] = round(
            (utc_now() - (_parse_dt(row.get("created_at")) or utc_now())).total_seconds() / 3600, 1
        )
        row["payment_state"] = "wallet_debited" if row["wallet_order"] else "unverified"

    if verify:
        for row in rows[:25]:
            if row["wallet_order"]:
                continue
            row["payment_state"] = _verify_paystack(row.get("paystack_ref")).get("state", "unverified")

    eligible_rows = [r for r in rows if r["eligible"]]
    return {
        "status": True, "window_days": days, "page": page, "page_size": page_size,
        "total": total,
        "eligible_on_page": len(eligible_rows),
        "value_on_page": _money(sum(_num(r.get("price")) for r in eligible_rows)),
        "orders": rows,
    }


@router.get("/stranded")
def dashxera_stranded_legacy(
    days: int = Query(7), verify: bool = Query(False),
    actor: str = Depends(require_dashxera_admin),
):
    """v1 path, kept for rollout safety."""
    return dashxera_undispatched(days=days, verify=verify, page=1,
                                 page_size=MAX_PAGE_SIZE, _=actor)


def _verify_paystack(reference: Optional[str]) -> dict:
    if not reference:
        return {"state": "no_reference", "amount": 0.0}
    if str(reference).startswith(AGENT_REF_PREFIX):
        return {"state": "wallet_debited", "amount": 0.0}
    if not PAYSTACK_SECRET:
        return {"state": "verify_unavailable", "amount": 0.0}
    try:
        res = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"}, timeout=12,
        )
        data = (res.json() or {}).get("data") or {}
        state = str(data.get("status") or "unknown").lower()
        return {
            "state": "paid" if state == "success" else state,
            "amount": _num(data.get("amount")) / 100.0,
            "channel": data.get("channel"),
            "paid_at": data.get("paid_at"),
        }
    except Exception as exc:
        return {"state": "verify_error", "amount": 0.0, "error": str(exc)[:160]}


# ============================================================================
# REPROCESSING
# ============================================================================


def _audit(
    action: str, *, outcome: str, detail: str = "", actor: str = "admin",
    order_id=None, reference=None, provider=None,
    previous_status=None, new_status=None, provider_ref=None,
) -> None:
    try:
        _db().table("dashxera_actions").insert({
            "action": action, "order_id": order_id, "reference": reference,
            "provider": provider, "outcome": outcome, "detail": detail[:1000],
            "actor": actor, "previous_status": previous_status,
            "new_status": new_status, "provider_ref": provider_ref,
        }).execute()
    except Exception as exc:
        logger.warning("DASHXERA: audit write failed for order %s: %s", order_id, exc)


def _dispatch(order: dict, provider: str) -> dict:
    """
    Thin wrapper over main.py's own provider integrations. Nothing is
    reimplemented, so DashXera cannot drift from production behaviour.
    Returns {"ok", "ref", "order_id", "error"}.
    """
    network = str(order.get("network") or "")
    bundle = str(order.get("bundle") or "")
    phone = str(order.get("phone_number") or "")
    reference = str(order.get("paystack_ref") or order.get("evosdata_ref") or "")

    extract_capacity = _from_main("extract_capacity")
    network_map = _from_main("NETWORK_MAP", {})
    timeout = _from_main("REQUEST_TIMEOUT", 10)

    try:
        if provider == "DATAMART":
            api_key = _from_main("DATAMART_API_KEY") or os.getenv("DATAMART_API_KEY", "")
            base = _from_main("DATAMART_BASE", "https://api.datamartgh.shop/api/developer")
            res = requests.post(
                f"{base}/purchase",
                headers={"X-API-Key": api_key},
                json={
                    "phoneNumber": phone,
                    "network": network_map.get(network.upper(), network),
                    "capacity": extract_capacity(bundle) if extract_capacity else bundle,
                    "gateway": "wallet",
                },
                timeout=timeout,
            )
            payload = res.json()
            data = payload.get("data") or {}
            if not data.get("orderReference"):
                return {"ok": False, "error": payload.get("message") or json.dumps(payload)[:400]}
            return {"ok": True, "ref": data.get("orderReference"), "order_id": data.get("orderId")}

        if provider == "BUNDLES_GHANA":
            call_bg = _from_main("call_bundles_ghana")
            if not call_bg:
                return {"ok": False, "error": "call_bundles_ghana unavailable"}
            name_map = {"MTN": "MTN", "TELECEL": "Telecel", "AIRTELTIGO": "AirtelTigo", "AT": "AirtelTigo"}
            network_name = name_map.get(network.upper(), network)
            listing = call_bg(f"/bundles?network={network_name}")
            if not listing.get("success"):
                return {"ok": False, "error": f"Bundles Ghana fetch failed: {listing.get('error')}"}

            wanted = bundle.upper().replace(" ", "")
            match = next(
                (b for b in listing.get("bundles", [])
                 if str(b.get("volume", "")).upper().replace(" ", "") == wanted
                 and b.get("status") == "active"),
                None,
            )
            if not match:
                return {"ok": False, "error": f"No active BG bundle for {network_name} {wanted}"}

            placed = call_bg("/order", method="POST", body={
                "bundle_id": match["id"], "phone": phone,
                "webhook_url": "https://api.evosdata.xyz/webhook/bundlesghana",
            })
            if not placed.get("success"):
                return {"ok": False, "error": f"BG order failed: {placed.get('error') or placed.get('message')}"}
            return {"ok": True, "ref": placed["order"]["reference"], "order_id": str(placed["order"]["id"])}

        if provider == "SWIFT_DATA_LINK":
            call_sdl = _from_main("call_swift_data_link")
            if not call_sdl:
                return {"ok": False, "error": "call_swift_data_link unavailable"}
            volume = float(extract_capacity(bundle) or 0) if extract_capacity else 0
            placed = call_sdl(network=network, volume=volume, phone=phone)
            if not placed.get("success"):
                return {"ok": False, "error": f"SDL order failed: {placed.get('error') or placed}"}
            return {"ok": True, "ref": placed.get("reference"), "order_id": placed.get("orderId")}

        if provider == "AGYEKUMDATA":
            get_package = _from_main("get_agyekumdata_package_id")
            call_agd = _from_main("call_agyekumdata_purchase")
            sanitise = _from_main("sanitise_agyekumdata_ref")
            if not (get_package and call_agd):
                return {"ok": False, "error": "Agyekumdata helpers unavailable"}
            placed = call_agd(package_id=get_package(network, bundle), phone=phone,
                              client_reference=reference)
            if not placed.get("success"):
                return {"ok": False, "error": f"AGYEKUMDATA order failed: {placed.get('error') or placed}"}
            data = placed.get("data") or {}
            return {
                "ok": True,
                "ref": data.get("clientReference") or (sanitise(reference) if sanitise else reference),
                "order_id": data.get("orderId"),
            }

        return {"ok": False, "error": f"Unknown provider {provider}"}

    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}


class ReprocessRequest(BaseModel):
    provider: Optional[str] = Field(None, max_length=40)
    force: bool = Field(False, description="Dispatch without a Paystack confirmation")


_reprocess_locks: Dict[int, threading.Lock] = {}
_reprocess_locks_guard = threading.Lock()


def _order_lock(order_id: int) -> threading.Lock:
    with _reprocess_locks_guard:
        return _reprocess_locks.setdefault(order_id, threading.Lock())


def _reprocess_one(order_id: int, payload: ReprocessRequest, actor: str) -> dict:
    """
    Duplicate protection runs at three levels:
      1. A non-blocking per-order lock, so two admins clicking at once can't
         both get through in this process.
      2. A fresh read of the order at entry, checked against _is_eligible.
      3. A second read of datamart_ref and status immediately before the
         provider call, which catches the background retry job claiming the
         order while we were talking to Paystack.

    force bypasses the *payment verification* only. It never bypasses an
    already-dispatched or already-fulfilled order — that path is what sends a
    customer two bundles, so it stays closed.
    """
    db = _db()
    lock = _order_lock(order_id)

    if not lock.acquire(blocking=False):
        return {"order_id": order_id, "outcome": "skipped",
                "reason": "Another reprocess of this order is already running"}

    previous_status = None
    try:
        found = db.table("orders").select("*").eq("id", order_id).limit(1).execute()
        if not found.data:
            return {"order_id": order_id, "outcome": "skipped", "reason": "Order not found"}

        order = found.data[0]
        previous_status = order.get("status")
        eligible, reason = _is_eligible(order)

        # Fulfilment guards are absolute. Everything else may be forced.
        hard_block = order.get("datamart_ref") or str(previous_status or "").lower() in STATUS_SUCCESS
        if not eligible and (hard_block or not payload.force):
            _audit("reprocess", outcome="skipped", detail=reason, actor=actor,
                   order_id=order_id, reference=order.get("paystack_ref"),
                   previous_status=previous_status, new_status=previous_status)
            return {"order_id": order_id, "outcome": "skipped", "reason": reason}

        reference = order.get("paystack_ref")
        payment = _verify_paystack(reference)

        if payment["state"] not in ("paid", "wallet_debited") and not payload.force:
            detail = f"Payment not confirmed ({payment['state']})"
            _audit("reprocess", outcome="skipped", detail=detail, actor=actor,
                   order_id=order_id, reference=reference,
                   previous_status=previous_status, new_status=previous_status)
            return {"order_id": order_id, "outcome": "skipped", "reason": detail, "payment": payment}

        # Money is confirmed in. Reflect that before dispatching, so a crash
        # mid-flight leaves a recoverable row rather than pending_payment.
        if str(previous_status or "").lower() in STATUS_AWAITING + STATUS_FAILED:
            db.table("orders").update({"status": "paid"}).eq("id", order_id).execute()

        provider = (payload.provider or "").strip().upper() or None
        chain_fn = _from_main("get_provider_chain")
        chain: List[str] = []
        if chain_fn:
            try:
                chain = [p for p in (chain_fn(order.get("network")) or []) if p]
            except Exception:
                chain = []
        if not chain:
            single = _from_main("get_provider")
            if single:
                chain = [p for p in [single(order.get("network"))] if p]

        if provider:
            if chain and provider not in chain:
                return {"order_id": order_id, "outcome": "skipped",
                        "reason": f"{provider} is not in the routing chain for {order.get('network')}"}
        else:
            if not chain:
                return {"order_id": order_id, "outcome": "failed",
                        "reason": "No provider configured for this network"}
            index = min(max(int(order.get("provider_priority") or 1) - 1, 0), len(chain) - 1)
            provider = chain[index]

        # Last guard before the money-moving call.
        recheck = db.table("orders").select("datamart_ref, status").eq("id", order_id).limit(1).execute()
        if recheck.data:
            fresh = recheck.data[0]
            if fresh.get("datamart_ref"):
                return {"order_id": order_id, "outcome": "skipped",
                        "reason": "Dispatched by the retry job while this ran"}
            if str(fresh.get("status") or "").lower() in STATUS_SUCCESS:
                return {"order_id": order_id, "outcome": "skipped",
                        "reason": "Fulfilled while this ran"}

        result = _dispatch(order, provider)

        if not result.get("ok"):
            error = result.get("error") or "Provider rejected the order"
            db.table("orders").update({
                "last_error": error[:500],
                "reprocess_count": int(order.get("reprocess_count") or 0) + 1,
                "reprocessed_at": utc_now().isoformat(),
            }).eq("id", order_id).execute()

            record_provider_incident(
                provider, f"Manual reprocess of order {order_id} failed: {error}",
                kind="reprocess_failed" if classify_provider_error(error) == "purchase_failed" else None,
                order_id=order_id, reference=reference,
                network=order.get("network"), bundle=order.get("bundle"),
            )
            _audit("reprocess", outcome="failed", detail=error, actor=actor,
                   order_id=order_id, reference=reference, provider=provider,
                   previous_status=previous_status, new_status="paid")
            return {"order_id": order_id, "outcome": "failed", "reason": error, "provider": provider}

        db.table("orders").update({
            "status": "processing",
            "datamart_ref": result.get("ref"),
            "datamart_order_id": str(result.get("order_id")) if result.get("order_id") else None,
            "dispatch_provider": provider,
            "reprocessed_at": utc_now().isoformat(),
            "reprocess_count": int(order.get("reprocess_count") or 0) + 1,
            "last_error": None,
        }).eq("id", order_id).execute()

        # Agent margin is credited on dispatch, exactly as the webhook does.
        profit_fn = _from_main("process_agent_profit")
        if profit_fn and order.get("agent_id") and reference:
            try:
                profit_fn(order_id, reference)
            except Exception as exc:
                logger.warning("DASHXERA: agent profit for order %s failed: %s", order_id, exc)

        _audit("reprocess", outcome="success", detail=f"dispatched via {provider}", actor=actor,
               order_id=order_id, reference=reference, provider=provider,
               previous_status=previous_status, new_status="processing",
               provider_ref=result.get("ref"))

        return {
            "order_id": order_id, "outcome": "success", "provider": provider,
            "provider_ref": result.get("ref"), "previous_status": previous_status,
            "new_status": "processing", "payment": payment,
        }
    except Exception as exc:
        logger.error("DASHXERA: reprocess of order %s errored: %s", order_id, exc)
        _audit("reprocess", outcome="failed", detail=str(exc)[:500], actor=actor,
               order_id=order_id, previous_status=previous_status)
        return {"order_id": order_id, "outcome": "failed", "reason": str(exc)[:300]}
    finally:
        lock.release()


@router.post("/reprocess/{order_id}")
def dashxera_reprocess(
    order_id: int,
    payload: Optional[ReprocessRequest] = None,
    actor: str = Depends(require_dashxera_admin),
):
    return {"status": True, **_reprocess_one(order_id, payload or ReprocessRequest(), actor)}


class BulkReprocessRequest(BaseModel):
    order_ids: List[int]
    force: bool = False
    provider: Optional[str] = None


@router.post("/reprocess-bulk")
def dashxera_reprocess_bulk(
    payload: BulkReprocessRequest,
    actor: str = Depends(require_dashxera_admin),
):
    order_ids = list(dict.fromkeys(payload.order_ids))
    if not order_ids:
        raise HTTPException(400, "Select at least one order")
    if len(order_ids) > 50:
        raise HTTPException(400, "Reprocess at most 50 orders at a time")

    single = ReprocessRequest(provider=payload.provider, force=payload.force)
    results = []
    for order_id in order_ids:
        # Each order is re-read and re-checked inside _reprocess_one, so a long
        # batch never acts on a snapshot taken when the batch started.
        results.append(_reprocess_one(order_id, single, actor))
        time.sleep(0.25)  # don't machine-gun the provider API

    tally: Dict[str, int] = defaultdict(int)
    for row in results:
        tally[row["outcome"]] += 1

    return {"status": True, "summary": dict(tally), "results": results}


@router.get("/audit")
def dashxera_audit(
    days: int = Query(7),
    order_id: Optional[int] = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    _: str = Depends(require_dashxera_admin),
):
    days = _window(days)
    since_iso = (utc_now() - timedelta(days=days)).isoformat()
    offset = (page - 1) * page_size

    try:
        query = _db().table("dashxera_actions").select("*", count="exact").gte("created_at", since_iso)
        if order_id:
            query = query.eq("order_id", order_id)
        result = (query.order("created_at", desc=True)
                  .range(offset, offset + page_size - 1).execute())
        return {
            "status": True, "window_days": days, "page": page, "page_size": page_size,
            "total": getattr(result, "count", None), "actions": result.data or [],
        }
    except Exception as exc:
        logger.warning("DASHXERA: audit read failed: %s", exc)
        return {"status": True, "window_days": days, "actions": [], "total": 0,
                "note": "Audit table unavailable — run the DashXera migration"}


# ============================================================================
# ATTENTION FEED
# ============================================================================


@router.get("/attention")
def dashxera_attention(days: int = Query(7), actor: str = Depends(require_dashxera_admin)):
    """Everything an admin needs to act on, in one call for the overview page."""
    days = _window(days)
    since_iso = (utc_now() - timedelta(days=days)).isoformat()
    items = []

    row = _summary_row(since_iso)
    undispatched = int(row.get("undispatched_orders") or 0)
    if undispatched:
        items.append({
            "kind": "undispatched", "severity": "critical",
            "title": f"{undispatched} paid order{'' if undispatched == 1 else 's'} never dispatched",
            "detail": f"GHS {_money(row.get('undispatched_value'))} collected with no provider reference",
            "link": "undispatched",
        })

    try:
        for provider in dashxera_providers(days=days, _=actor).get("attention", []):
            items.append({
                "kind": "provider", "severity": "critical",
                "title": f"{provider['provider']} is {provider['health']}",
                "detail": provider.get("latest_low_balance")
                          or f"{provider.get('failed_orders', 0)} failed orders in this window",
                "link": "providers",
            })
    except Exception as exc:
        logger.warning("DASHXERA: provider health unavailable: %s", exc)

    try:
        incidents = dashxera_incidents(days=days, include_resolved=False, kind=None,
                                       page=1, page_size=5, _=actor)
        for inc in incidents.get("incidents", []):
            if inc.get("severity") != "critical":
                continue
            items.append({
                "kind": "incident", "severity": "critical",
                "title": f"{inc.get('provider')}: {inc.get('kind')}",
                "detail": (inc.get("message") or "")[:200],
                "link": "incidents",
            })
    except Exception:
        pass

    return {"status": True, "window_days": days, "items": items, "count": len(items)}


# ============================================================================
# MOUNT
# ============================================================================


def install(app, enable_log_capture: bool = True) -> None:
    app.include_router(router)
    _ensure_worker()
    if enable_log_capture:
        install_log_capture()
    logger.info("DASHXERA: mounted at /admin/dashxera")
