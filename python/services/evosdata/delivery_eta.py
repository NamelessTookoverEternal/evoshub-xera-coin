"""
Live delivery estimate for the tracking page.

Looks at how long the most recent orders on the same network really took to arrive and turns that into an
honest message, so the page says "10 - 30 minutes" on a fast day and "1 - 2 hours" on a slow one:

    typical delivery        message
    up to 10 min            usually arrives within about 10 minutes
    10 - 30 min             usually arrives within 10 - 30 minutes
    30 - 60 min             usually arrives within 30 - 60 minutes
    1 - 2 hours             taking about 1 - 2 hours at the moment
    over 2 hours            slower than usual, a little validation may be ongoing, up to about 4 hours

An order that has already waited longer than the estimate is moved to the band it is actually in, so a
3-hour-old order never keeps saying "10 minutes".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from statistics import median

logger = logging.getLogger("delivery_eta")

SAMPLE_SIZE = 10          # most recent deliveries per network
SAMPLE_WINDOW_HOURS = 24  # ignore anything older than this
MIN_SAMPLES = 3           # fewer than this: fall back to the default
DEFAULT_MINUTES = 20.0

# (upper bound in minutes, message)
BANDS = [
    (10, "Usually arrives within about 10 minutes."),
    (30, "Usually arrives within 10 - 30 minutes."),
    (60, "Usually arrives within 30 - 60 minutes."),
    (120, "Deliveries are taking about 1 - 2 hours at the moment."),
    (None, "Delivery is slower than usual. A little validation may be ongoing, so it can take up to about 4 hours."),
]


def _dt(raw) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def band_index(minutes: float) -> int:
    for i, (upper, _) in enumerate(BANDS):
        if upper is None or minutes <= upper:
            return i
    return len(BANDS) - 1


def estimate_text(typical_minutes: float, waited_minutes: float = 0.0) -> str:
    """Message for an order. `typical` is the recent median; `waited` moves it up if the order is already late."""
    i = max(band_index(typical_minutes), band_index(waited_minutes))
    return BANDS[i][1]


def recent_typical_minutes(db, network: str, now: datetime | None = None) -> float:
    """Median delivery time (minutes) of the latest deliveries on this network; DEFAULT_MINUTES if too few."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=SAMPLE_WINDOW_HOURS)).isoformat()
    try:
        rows = db.table("orders").select("created_at, delivered_at").eq("network", network) \
            .not_.is_("delivered_at", "null").gte("delivered_at", since) \
            .order("delivered_at", desc=True).limit(SAMPLE_SIZE).execute().data or []
    except Exception as exc:                      # column not there yet / DB hiccup: the default still works
        logger.info("delivery eta: no samples (%s)", exc)
        return DEFAULT_MINUTES
    mins = []
    for r in rows:
        a, b = _dt(r.get("created_at")), _dt(r.get("delivered_at"))
        if a and b and b >= a:
            mins.append((b - a).total_seconds() / 60.0)
    return float(median(mins)) if len(mins) >= MIN_SAMPLES else DEFAULT_MINUTES


def enrich(db, orders: list[dict], now: datetime | None = None) -> list[dict]:
    """Adds `eta_text` to orders that are still on their way (paid / processing). Never raises."""
    now = now or datetime.now(timezone.utc)
    cache: dict[str, float] = {}
    for o in orders:
        if o.get("status") not in ("paid", "processing"):
            continue
        try:
            net = o.get("network") or ""
            if net not in cache:
                cache[net] = recent_typical_minutes(db, net, now)
            placed = _dt(o.get("created_at")) or now
            o["eta_text"] = estimate_text(cache[net], (now - placed).total_seconds() / 60.0)
        except Exception as exc:
            logger.warning("delivery eta failed: %s", exc)
    return orders
