"""
Product switches: which ecosystem products are currently ON.

Read by the public status route (greys tiles) and by the guards on EVOS Data / EVOSGPT
(refuse NEW orders and chats while a product is off and enforcement is on).

Design rules:
  * FAIL OPEN. If the table is missing or the database errors, every product counts as ON,
    so one failed request never switches the ecosystem off. The last good answer is reused
    for a short while before falling back to "all on".
  * A missing row means ON.
  * Only new orders/chats are guarded. Paystack and provider webhooks, order status/sync and
    order tracking are never guarded, so a customer who already paid always gets served.
"""
import logging
import threading
import time

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# product_key -> label, whether the backend refuses new activity by default
PRODUCTS = {
    "evosdata": ("EVOS Data", True),
    "evosgpt": ("EVOSGPT", True),
    "xera": ("XERA", False),
    "games": ("Africa Games", False),
    "roadmap": ("Roadmap", False),
    "website": ("Website creation", False),
}
# Switching these off affects people's money or access, so the admin console asks for confirmation.
SENSITIVE = {"xera"}

CACHE_SECONDS = 10
STALE_OK_SECONDS = 300   # keep serving the last good answer this long if the database is failing

_lock = threading.Lock()
_cache = {"at": 0.0, "ok_at": 0.0, "data": None}


def _client():
    from utils.xera_supabase import supabase
    return supabase


def default_snapshot() -> dict:
    return {k: {"label": v[0], "enabled": True, "enforce": v[1], "message": None} for k, v in PRODUCTS.items()}


def _load() -> dict:
    rows = _client().table("product_switches").select("*").execute().data or []
    snap = default_snapshot()
    for r in rows:
        key = r.get("product_key")
        if key not in snap:
            continue
        snap[key].update({
            "enabled": bool(r.get("enabled", True)),
            "enforce": bool(r.get("enforce", snap[key]["enforce"])),
            "message": (r.get("message") or None),
        })
    return snap


def snapshot(force: bool = False) -> dict:
    now = time.time()
    with _lock:
        if not force and _cache["data"] is not None and now - _cache["at"] < CACHE_SECONDS:
            return _cache["data"]
    try:
        data = _load()
        with _lock:
            _cache.update(at=now, ok_at=now, data=data)
        return data
    except Exception as exc:
        logger.warning("product_switches: could not read switches (%r); failing open", exc)
        with _lock:
            if _cache["data"] is not None and now - _cache["ok_at"] < STALE_OK_SECONDS:
                _cache["at"] = now
                return _cache["data"]
        return default_snapshot()


def clear_cache() -> None:
    with _lock:
        _cache.update(at=0.0, ok_at=0.0, data=None)


def is_blocked(key: str) -> bool:
    p = snapshot().get(key)
    return bool(p and not p["enabled"] and p["enforce"])


def block_message(key: str) -> str:
    p = snapshot().get(key) or {}
    label = p.get("label") or key
    return p.get("message") or f"{label} is switched off for now. Please check back soon."


def require_on(key: str):
    """FastAPI dependency: `dependencies=[Depends(require_on("evosdata"))]` on routes that START new activity."""
    def _dep():
        if is_blocked(key):
            raise HTTPException(status_code=503, detail=block_message(key), headers={"Retry-After": "300"})
    _dep.__name__ = f"require_{key}_on"
    return _dep
