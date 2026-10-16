"""
EVOS Data Services routes, served by the Hub backend.

Everything is mounted at /api/evosdata (no collisions with Hub or XERA routes):
    core router      services/evosdata/core.py   (orders, wallet, Paystack, providers, auth, admin)
    + spin, agent-fee, DashXera admin dashboard, EVOXERA WhatsApp bot

Webhook ALIASES: provider/Paystack/WhatsApp webhooks are also registered at their
historical root paths (/webhook/*, /whatsapp/*, /ussd) so that pointing
api.evosdata.xyz at this backend needs no dashboard changes. Both paths run the
same handler, so there is no duplicate processing — a provider only ever calls
the one URL it is configured with.

Set EVOSDATA_ENABLED=false to boot the Hub without Evosdata (e.g. before its
environment variables are in place). With it enabled (default), missing required
variables stop startup — same fail-fast behaviour as the standalone app.
Set EVOSDATA_BACKGROUND_JOBS=false to mount the routes without starting the retry loops.
"""
import logging
import os

from fastapi import APIRouter, FastAPI

logger = logging.getLogger(__name__)

PREFIX = "/api/evosdata"
_LEGACY_PREFIXES = ("/webhook", "/whatsapp", "/ussd")


def background_jobs_enabled() -> bool:
    """Retry loops (stuck orders/deposits/withdrawals, agent-fee activation, bot notifier).

    Set EVOSDATA_BACKGROUND_JOBS=false on the Hub while the standalone Evosdata backend is
    still running against the same database, so the two never retry the same rows.
    """
    return os.getenv("EVOSDATA_BACKGROUND_JOBS", "true").strip().lower() not in ("0", "false", "no", "off")


def evosdata_enabled() -> bool:
    return os.getenv("EVOSDATA_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


class _Mount:
    """Lets the side modules' install(app) hooks mount under the Evosdata prefix."""

    def __init__(self, app: FastAPI, router: APIRouter):
        self._app, self._router = app, router

    def include_router(self, r, **kw):
        self._router.include_router(r, **kw)

    def on_event(self, name):
        if not background_jobs_enabled():
            return lambda fn: fn          # hook dropped: loop never starts
        return self._app.on_event(name)


def mount_evosdata(app: FastAPI, prefix: str = PREFIX) -> bool:
    if not evosdata_enabled():
        logger.warning("EVOSDATA: disabled (EVOSDATA_ENABLED=false) — routes not mounted")
        return False

    from services.evosdata import core

    if core.MISSING_ENVS:
        raise RuntimeError("EVOSDATA: missing environment variables: " + ", ".join(core.MISSING_ENVS))

    router = APIRouter()
    router.include_router(core.router)

    # Optional modules: a failure in one must never take the API down (as before).
    mount = _Mount(app, router)
    for name in ("dashxera", "evoxera_bot", "spin", "agent_fee"):
        try:
            __import__(f"services.evosdata.{name}", fromlist=["install"]).install(mount)
        except Exception as exc:
            logger.error("EVOSDATA %s: failed to mount (%s) — API continues without it", name.upper(), exc)

    # Background retry loops the standalone app started on startup (unchanged function).
    if background_jobs_enabled():
        app.on_event("startup")(core.startup_event)
    else:
        logger.warning("EVOSDATA: background retry jobs disabled (EVOSDATA_BACKGROUND_JOBS=false)")

    app.include_router(router, prefix=prefix, tags=["evosdata"])

    legacy = APIRouter()
    if prefix:  # (prefix="" is used by unit tests; the root paths already exist then)
        for r in router.routes:
            if getattr(r, "path", "").startswith(_LEGACY_PREFIXES):
                legacy.routes.append(r)
        app.include_router(legacy, tags=["evosdata-legacy-webhooks"])

    logger.info("EVOSDATA: mounted at %s (+ %d legacy webhook aliases)", prefix or "/", len(legacy.routes))
    return True
