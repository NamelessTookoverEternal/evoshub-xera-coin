"""
XERA referral API — mounted in main.py as:

    app.include_router(xera_referral_router, prefix="/api/xera/referral", tags=["xera-referral"])

  GET /validate?code=…   public  — greets an invitee ("Kofi invited you")
  GET /me                session — my code, invite link, stats, who invited me
"""

import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from utils.rate_limit import limiter
from utils.supabase_admin import (
    get_public_user_by_referral_code,
    link_referral,
)
from utils.xera_supabase import supabase
from xera.referrals import clean_ref, mask_username, new_unique_code
from xera.user_auth import verify_user_token, XeraTokenInvalid

logger = logging.getLogger(__name__)
router = APIRouter()

_INVITE_BASE = os.getenv("XERA_INVITE_BASE_URL", "https://evoshub.xyz/xera/invite").rstrip("/")


def invite_link(code: str) -> str:
    return f"{_INVITE_BASE}?ref={code}"


@router.get("/validate")
@limiter.limit("30/minute")
async def validate_referral(request: Request, code: str = ""):
    cleaned = clean_ref(code)
    if not cleaned:
        return {"valid": False}
    owner = await get_public_user_by_referral_code(cleaned)
    if not owner:
        return {"valid": False}
    # Only a display name — no id, email or anything else about the inviter.
    display = (owner.get("full_name") or owner.get("username") or "").strip().split(" ")[0]
    return {"valid": True, "inviter": display or "A friend", "code": owner["referral_code"]}


def _load_me(user_id: int) -> dict:
    """Sync Supabase reads for /me (run in a threadpool)."""
    user = (
        supabase.table("users")
        .select("id,username,referral_code,referred_by")
        .eq("id", user_id).limit(1).execute()
    ).data
    if not user:
        raise HTTPException(status_code=404, detail="Account not found.")
    user = user[0]

    rows = (
        supabase.table("xera_referrals")
        .select("referred_user_id,status,reward_amount,qualified_at,created_at,source_product", count="exact")
        .eq("referrer_user_id", user_id)
        .order("created_at", desc=True)
        .limit(1000)
        .execute()
    )
    referrals = rows.data or []
    total = rows.count if rows.count is not None else len(referrals)

    names = {}
    ids = [r["referred_user_id"] for r in referrals[:20]]
    if ids:
        for u in (supabase.table("users").select("id,username").in_("id", ids).execute().data or []):
            names[u["id"]] = u.get("username")

    cfg = (supabase.table("xera_config").select("referral_enabled").eq("id", 1).limit(1).execute().data or [{}])[0]
    rcfg = (supabase.table("xera_referral_config").select("referrer_reward,referee_reward").eq("id", 1).limit(1).execute().data or [{}])[0]

    return {
        "user": user,
        "referrals": referrals,
        "total": total,
        "names": names,
        "enabled": bool(cfg.get("referral_enabled")),
        "referrer_reward": float(rcfg.get("referrer_reward") or 0),
        "referee_reward": float(rcfg.get("referee_reward") or 0),
    }


@router.get("/me")
@limiter.limit("30/minute")
async def my_referral(request: Request, authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id = verify_user_token(token)
    except XeraTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")

    data = await run_in_threadpool(_load_me, user_id)
    user = data["user"]

    # Accounts created before referrals existed have no code yet.
    code = user.get("referral_code")
    if not code:
        code = await new_unique_code(user.get("username") or "")
        await run_in_threadpool(
            lambda: supabase.table("users").update({"referral_code": code})
            .eq("id", user_id).is_("referral_code", "null").execute()
        )
        # Another request may have won the race; re-read the winner.
        fresh = await run_in_threadpool(
            lambda: supabase.table("users").select("referral_code").eq("id", user_id).limit(1).execute().data
        )
        code = (fresh[0]["referral_code"] if fresh and fresh[0].get("referral_code") else code)

    # Cross-product sync: someone referred inside EVOSGPT / EVOS Data has
    # users.referred_by set but no xera_referrals row until they open XERA.
    invited_by = None
    if user.get("referred_by"):
        try:
            await link_referral(user_id, None, "ecosystem")
        except Exception as e:  # never break the dashboard over referral bookkeeping
            logger.error("XERA REFERRAL SYNC FAILED: %s", str(e))
        inviter = await get_public_user_by_referral_code(user["referred_by"])
        if inviter:
            invited_by = (inviter.get("full_name") or inviter.get("username") or "").strip().split(" ")[0] or None

    refs = data["referrals"]
    qualified = [r for r in refs if r.get("qualified_at")]
    earned = sum(float(r.get("reward_amount") or 0) for r in refs if r.get("status") == "rewarded")

    return {
        "status": "ok",
        "code": code,
        "link": invite_link(code),
        "invited_by": invited_by,
        "stats": {
            "total": data["total"],
            "qualified": len(qualified),
            "pending": max(data["total"] - len(qualified), 0),
            "earned": earned,
        },
        "rewards": {
            "enabled": data["enabled"],
            "referrer_reward": data["referrer_reward"],
            "referee_reward": data["referee_reward"],
        },
        "recent": [
            {
                "name": mask_username(data["names"].get(r["referred_user_id"])),
                "status": r.get("status"),
                "joined": r.get("created_at"),
                "source": r.get("source_product"),
            }
            for r in refs[:20]
        ],
    }
