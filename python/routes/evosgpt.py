"""
EVOSGPT, served by the Hub backend.

Everything is mounted at /api/evosgpt (no collisions with the Hub, XERA or EVOS Data):
    POST /api/evosgpt/auth/login | /auth/register | /auth/hub-session
    POST /api/evosgpt/chat | /image/generate | /image/edit | /document/generate
    GET  /api/evosgpt/currency            visitor currency (default GHS)
    POST /api/evosgpt/upgrade/init        GET /api/evosgpt/upgrade/verify/{reference}
    POST /api/evosgpt/webhook/paystack

Unlike EVOS Data there are NO root-path aliases: /webhook/paystack at the root belongs to
EVOS Data. If the Paystack dashboard webhook points at EVOS Data's URL, EVOSGPT upgrades
still complete through /upgrade/verify when the customer returns to the app.

EVOSGPT_ENABLED=false boots the Hub without it. A failure while mounting is logged and never
takes the rest of the API down.
"""
import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)

PREFIX = "/api/evosgpt"


def evosgpt_enabled() -> bool:
    return os.getenv("EVOSGPT_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def mount_evosgpt(app: FastAPI, prefix: str = PREFIX) -> bool:
    if not evosgpt_enabled():
        logger.warning("EVOSGPT: disabled (EVOSGPT_ENABLED=false) — routes not mounted")
        return False
    try:
        from services.evosgpt import core
        if core.MISSING_ENVS:
            logger.warning("EVOSGPT: missing environment variables (feature degraded): %s", ", ".join(core.MISSING_ENVS))
        core.install(app)
        app.include_router(core.router, prefix=prefix, tags=["evosgpt"])
    except Exception as exc:
        logger.error("EVOSGPT: failed to mount (%s) — API continues without it", exc)
        return False
    logger.info("EVOSGPT: mounted at %s", prefix)
    return True
