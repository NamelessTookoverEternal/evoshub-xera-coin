"""
IP risk note (VPN / proxy) for XERA P2P transfers.

This is INFORMATION ONLY. It never blocks or slows a transfer by more than a
short lookup, and any failure returns {"vpn": None, "checked": False}. The result is stored with the
transfer so the admin review page can show "VPN used" next to the IP.

Setup (optional, keys go ONLY in Render env, never in chat or code):
    XERA_IP_INTEL_PROVIDER=proxycheck      # leave unset to switch the check off
    XERA_IP_INTEL_API_KEY=<your proxycheck.io key>

Without those two variables nothing is looked up and ip_risk is stored as
{"vpn": null, "checked": false}: the IP address itself is still recorded.
"""

import ipaddress
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 2.5          # seconds; a slow checker must not hold up a transfer
_TTL = 6 * 3600         # same IP is not looked up again for 6 hours
_CACHE_MAX = 2000
_cache: dict[str, tuple[float, dict]] = {}


def configured() -> bool:
    return bool(os.getenv("XERA_IP_INTEL_PROVIDER", "").strip().lower() == "proxycheck"
                and os.getenv("XERA_IP_INTEL_API_KEY", "").strip())


def _unchecked() -> dict:
    return {"vpn": None, "checked": False}


def check_ip(ip: str | None) -> dict:
    """Returns {"vpn": bool|None, "checked": bool, "provider"?: str, "type"?: str}."""
    if not ip or not configured():
        return _unchecked()
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return _unchecked()
    if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
        return _unchecked()

    key = str(addr)
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]

    try:
        r = requests.get(
            f"https://proxycheck.io/v2/{key}",
            params={"key": os.getenv("XERA_IP_INTEL_API_KEY", "").strip(), "vpn": 1},
            timeout=_TIMEOUT,
        )
        data = r.json() if r.ok else {}
        info = data.get(key) if isinstance(data, dict) else None
        if data.get("status") not in ("ok", "warning") or not isinstance(info, dict):
            return _unchecked()
        result = {
            "vpn": str(info.get("proxy", "")).lower() == "yes",
            "checked": True,
            "provider": "proxycheck",
        }
        if info.get("type"):
            result["type"] = str(info["type"])[:30]
    except Exception as e:  # network error, bad JSON, anything
        logger.warning("XERA IP check failed: %s", e)
        return _unchecked()

    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[key] = (time.time() + _TTL, result)
    return result
