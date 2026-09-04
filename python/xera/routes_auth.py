"""XERA Token authentication.
Uses the existing EVOS ecosystem users table and password system.
"""

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from passlib.context import CryptContext

from utils.rate_limit import limiter
from utils.supabase_admin import (
    get_public_user_by_identifier,
    create_public_user,
    PublicUserConflict,
)
from xera.user_auth import make_user_token

router = APIRouter()

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

    try:
        user = await create_public_user(
            username=username,
            email=email,
            full_name=data.full_name,
            password_hash=password_hash,
        )
    except PublicUserConflict:
        raise HTTPException(status_code=409, detail="Username or email is already taken.")

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
