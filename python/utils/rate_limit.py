"""
Shared slowapi Limiter, used by every route module so there's exactly one
limiter instance (and one consistent notion of "the client's IP") across
the whole API.

PROXY NOTE — read before deploying:
Most hosts (Render, Railway, Fly, Vercel, behind Cloudflare, etc.) put your
app behind a reverse proxy. In that setup the raw TCP connection is from
the proxy, not the visitor, so request.client.host is always the proxy's
IP and a naive per-IP rate limit either blocks everyone as one "client" or
blocks no one usefully.

The fix is to read the real client IP out of X-Forwarded-For — but ONLY
if you actually trust the immediate hop to have set that header honestly.
If your API is reachable directly from the internet (no proxy in front),
trusting X-Forwarded-For lets an attacker forge any IP they like and
dodge rate limits entirely. So this is opt-in via TRUST_PROXY_HEADERS.

Set TRUST_PROXY_HEADERS=true in your environment ONLY if you've confirmed
requests to this backend can only arrive through your known proxy/CDN
(e.g. it's not directly internet-reachable on another port/IP).
"""

import os

from slowapi import Limiter
from starlette.requests import Request

_TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() == "true"


def get_client_ip(request: Request) -> str:
    if _TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # X-Forwarded-For can be a chain "client, proxy1, proxy2" —
            # the left-most entry is the original client.
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=get_client_ip)
