"""XERA Token authentication.
Uses the existing EVOS ecosystem users table and password system.
"""

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from passlib.context import CryptContext

from utils.rate_limit import limiter
import logging

from utils.supabase_admin import (
    get_public_user_by_identifier,
    create_public_user,
    link_referral,
    PublicUserConflict,
)
from xera.referrals import clean_ref, new_unique_code
from xera.user_auth import make_user_token

router = APIRouter()
logger = logging.getLogger(__name__)

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)

_DUMMY_HASH = (
    "$2b$12$KIXzCq3C3T6tFkUd9nj6aO.WwSIFqh4fQieFzpxKx5Mj5.z1rklHC"
)


class XeraLoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=512)


@router.post("/login")
@limiter.limit("10/minute")
async def xera_login(
    request: Request,
    data: XeraLoginRequest,
):
    identifier = data.identifier.strip().lower()

    # Find the existing EVOS ecosystem user.
    user = await get_public_user_by_identifier(identifier)

    # Always verify against a bcrypt hash to reduce timing differences.
    stored_hash = (
        user.get("password")
        if user and user.get("password")
        else _DUMMY_HASH
    )

    try:
        valid = pwd_context.verify(
            data.password,
            stored_hash,
        )
    except Exception:
        valid = False

    # Same authentication behavior as EVOSGPT.
    if not user or not valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid username/email or password.",
        )

    # Successful XERA login.
    return {
        "status": "ok",

        "token": make_user_token(
            int(user["id"])
        ),

        "user": {
            "id": user["id"],
            "username": user.get("username"),
            "email": user.get("email"),
            "full_name": user.get("full_name"),
        },
    }


_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")


class XeraRegisterRequest(BaseModel):
    """
    For people who aren't already in the EVOS ecosystem. This creates a
    real row in the shared `users` table (same one EVOSGPT/EVOSDATA/admin
    use), so the account works across EVOS products, not just XERA.
    """
    username: str = Field(min_length=3, max_length=32)
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=512)
    # Optional phone, stored on the shared users row (EVOS Data uses it).
    phone: str | None = Field(default=None, max_length=20)

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str | None) -> str:
        v = (v or "").strip()
        if not v:
            return ""
        cleaned = re.sub(r"[\s\-()]", "", v)
        if not re.match(r"^\+?[0-9]{9,15}$", cleaned):
            raise ValueError("Enter a valid phone number, e.g. 0241234567.")
        return cleaned

    # Invite code from a referral link. Optional; an unknown/malformed code is
    # ignored rather than blocking signup (the invite page validates it first).
    ref: str | None = Field(default=None, max_length=64)

    @field_validator("ref")
    @classmethod
    def _validate_ref(cls, v: str | None) -> str | None:
        return clean_ref(v)

    @field_validator("username")
    @classmethod
    def _validate_username(cls, v: str) -> str:
        v = v.strip().lower()
        if not _USERNAME_RE.match(v):
            raise ValueError("Username must be 3-32 characters: letters, numbers, underscores only.")
        return v

    @field_validator("full_name")
    @classmethod
    def _validate_full_name(cls, v: str) -> str:
        return v.strip()


@router.post("/register")
@limiter.limit("5/minute")
async def xera_register(
    request: Request,
    data: XeraRegisterRequest,
):
    username = data.username
    email = str(data.email).strip().lower()

    # Check both identifiers up front so we can give a specific error —
    # create_public_user still guards against a concurrent-signup race.
    existing_username = await get_public_user_by_identifier(username)
    if existing_username:
        raise HTTPException(status_code=409, detail="That username is already taken.")
    existing_email = await get_public_user_by_identifier(email)
    if existing_email:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")

    password_hash = pwd_context.hash(data.password)

    # Every new account gets its own invite code at creation. Referral
    # plumbing is best-effort: if it isn't set up yet (migration not run) or
    # hiccups, the account is still created — /referral/me issues the code later.
    try:
        my_code = await new_unique_code(username)
    except Exception as e:
        logger.error("XERA REFERRAL CODE GENERATION FAILED: %s", str(e))
        my_code = None

    try:
        user = await create_public_user(
            username=username,
            email=email,
            full_name=data.full_name,
            password_hash=password_hash,
            referral_code=my_code,
            phone=data.phone or "",
        )
    except PublicUserConflict:
        raise HTTPException(status_code=409, detail="Username or email is already taken.")
    except RuntimeError as e:
        if not my_code or "referral_code" not in str(e):
            raise
        # Most likely users.referral_code doesn't exist yet. Retry without it.
        logger.error("XERA REGISTER WITH REFERRAL CODE FAILED, RETRYING WITHOUT: %s", str(e))
        my_code = None
        try:
            user = await create_public_user(
                username=username,
                email=email,
                full_name=data.full_name,
                password_hash=password_hash,
                phone=data.phone or "",
            )
        except PublicUserConflict:
            raise HTTPException(status_code=409, detail="Username or email is already taken.")

    # Attribute to whoever invited them. Sets users.referred_by (shared by
    # every EVOS product) and records the XERA referral. Must never fail the
    # signup — the account already exists at this point.
    referred = False
    if data.ref:
        try:
            referred = (await link_referral(int(user["id"]), data.ref, "xera")) is not None
        except Exception as e:
            logger.error("XERA REFERRAL LINK FAILED: %s", str(e))

    return {
        "status": "ok",
        "referral_code": my_code,
        "referred": referred,

        "token": make_user_token(
            int(user["id"])
        ),

        "user": {
            "id": user["id"],
            "username": user.get("username"),
            "email": user.get("email"),
            "full_name": user.get("full_name"),
        },
    }
