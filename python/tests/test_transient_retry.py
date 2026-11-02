"""
A GET that fails because the database connection was dropped while idle is retried once;
writes are never retried; other errors are not retried.
"""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from utils.transient_retry import TransientRetryMiddleware, is_transient_connection_error


def _app(counter, exc_factory):
    app = FastAPI()

    @app.api_route("/thing", methods=["GET", "POST"])
    def thing():
        counter["n"] += 1
        if counter["n"] == 1:
            raise exc_factory()
        return {"ok": True, "calls": counter["n"]}

    app.add_middleware(TransientRetryMiddleware)

    # mirror main.py: the catch-all sits OUTSIDE the retry
    from starlette.middleware.base import BaseHTTPMiddleware

    class CatchAll(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            try:
                return await call_next(request)
            except Exception:
                return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.add_middleware(CatchAll)
    return app


def _dropped():
    return httpx.RemoteProtocolError("Server disconnected")


def test_a_dropped_connection_on_a_get_is_retried_once_and_succeeds():
    c = {"n": 0}
    r = TestClient(_app(c, _dropped)).get("/thing")
    assert r.status_code == 200 and r.json() == {"ok": True, "calls": 2}


def test_a_post_is_never_retried():
    c = {"n": 0}
    r = TestClient(_app(c, _dropped)).post("/thing")
    assert r.status_code == 500
    assert c["n"] == 1          # the write ran once; it was not repeated


def test_other_errors_are_not_retried():
    c = {"n": 0}
    r = TestClient(_app(c, lambda: ValueError("bug"))).get("/thing")
    assert r.status_code == 500 and c["n"] == 1


def test_a_second_failure_still_surfaces_as_500_not_a_loop():
    c = {"n": 0}
    app = FastAPI()

    @app.get("/always")
    def always():
        c["n"] += 1
        raise _dropped()

    app.add_middleware(TransientRetryMiddleware)
    from starlette.middleware.base import BaseHTTPMiddleware

    class CatchAll(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            try:
                return await call_next(request)
            except Exception:
                return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.add_middleware(CatchAll)
    r = TestClient(app).get("/always")
    assert r.status_code == 500 and c["n"] == 2     # tried twice, then gave up


def test_error_detection_follows_the_cause_chain():
    try:
        try:
            raise httpx.RemoteProtocolError("Server disconnected")
        except Exception as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as e:
        assert is_transient_connection_error(e)
    assert not is_transient_connection_error(ValueError("x"))
