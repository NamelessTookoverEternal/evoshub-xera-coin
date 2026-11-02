"""
One-shot retry for read-only requests that fail because a pooled connection to the database
(Supabase) was closed while the app was idle.

Symptom in the logs:  Unhandled error on /api/xera/daily/status: RemoteProtocolError('Server disconnected')
The first request after a quiet period reuses a keep-alive connection the server already dropped;
a brand-new connection works. Retrying once is safe ONLY for requests that cannot change anything,
so this middleware retries GET/HEAD and nothing else. POST/PUT/PATCH/DELETE (claims, payments,
mining, KYC...) are never retried here: a repeated write could be applied twice.
"""
import httpx

try:  # httpcore's own errors can surface unwrapped in some versions
    import httpcore
    _TRANSIENT = (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.ConnectError,
                  httpcore.RemoteProtocolError, httpcore.ReadError, httpcore.WriteError, httpcore.ConnectError)
except Exception:  # pragma: no cover
    _TRANSIENT = (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.ConnectError)

_SAFE_METHODS = ("GET", "HEAD")


def is_transient_connection_error(exc: BaseException) -> bool:
    """True if `exc` (or the error it was raised from) is a dropped/stale connection."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, _TRANSIENT):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


class TransientRetryMiddleware:
    """
    Pure ASGI middleware (not BaseHTTPMiddleware: that cannot safely run the inner app twice).
    Retries a GET/HEAD once, and only if no part of a response has been sent yet.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            if started or not is_transient_connection_error(exc):
                raise
            print(f"Retrying {scope.get('method')} {scope.get('path')} once after a dropped connection: {exc!r}")
            await self.app(scope, receive, send)
