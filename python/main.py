"""
EVOS Business Hub — Backend API
Powered by EVOXERA TECHNOLOGY
Run:  uvicorn main:app --reload
Docs: http://localhost:8000/docs  (disabled automatically when ENVIRONMENT=production)
"""
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from routes import admin, contact, website_requests
from utils.rate_limit import limiter
from utils.xera_supabase import supabase
from xera.routes import router as xera_router
from xera.routes_admin import router as xera_admin_router
from xera.routes_auth import router as xera_auth_router
_IS_PROD = os.getenv("ENVIRONMENT", "development").strip().lower() == "production"
app = FastAPI(
    title="EVOS Business Hub API",
    description="Backend API for evoshub.xyz — EVOXERA TECHNOLOGY",
    version="1.0.0",
    # In production, don't hand out a free map of every endpoint/schema to
    # anyone who requests it. Keep /docs available in dev for convenience.
    docs_url=None if _IS_PROD else "/docs",
    redoc_url=None if _IS_PROD else "/redoc",
    openapi_url=None if _IS_PROD else "/openapi.json",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Without this, an unhandled exception propagates past CORSMiddleware
    # before it can attach Access-Control-Allow-Origin, and the browser
    # reports a confusing "CORS policy" error instead of the real 500 —
    # this is exactly what happened with the missing Supabase env vars.
    print(f"Unhandled error on {request.url.path}: {exc!r}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "https://evoshub.xyz,http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Belt-and-suspenders headers for a JSON API. The frontend (Vercel) sets
    its own equivalent headers for the HTML it serves — these cover direct
    hits to the API domain itself (e.g. someone opening the API URL
    directly, or a misconfigured client rendering a response as HTML).

    /docs, /redoc, and /openapi.json are the one exception: Swagger UI and
    Redoc are real HTML pages that need to load JS/CSS from a CDN and run
    inline scripts, so they get a looser CSP scoped to just those paths.
    'self' resolves to whatever origin serves the response — on Render
    that's https://evoxera.onrender.com, no hardcoding needed. This branch
    is also dead code in production anyway, since docs_url is None there.
    """
    _DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        if request.url.path in self._DOCS_PATHS:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' https://fastapi.tiangolo.com data:; "
                "font-src 'self' https://cdn.jsdelivr.net; "
                "connect-src 'self';"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"

        if _IS_PROD:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(admin.router, prefix="/api")
app.include_router(contact.router, prefix="/api")
app.include_router(website_requests.router, prefix="/api")
app.include_router(xera_auth_router, prefix="/api/xera/auth", tags=["xera-auth"])
app.include_router(xera_router, prefix="/api/xera", tags=["xera"])
app.include_router(xera_admin_router, prefix="/api/admin/xera", tags=["xera-admin"])
@app.get("/")
@app.head("/")
def root():
    return {
        "status": "ok",
        "platform": "EVOS Business Hub",
        "powered_by": "EVOXERA TECHNOLOGY",
        "docs": None if _IS_PROD else "/docs",
    }

