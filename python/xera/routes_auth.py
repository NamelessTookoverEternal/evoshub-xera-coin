"""XERA Token (Coin) authentication. Only XERA exposes this user login flow."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from passlib.context import CryptContext
from utils.rate_limit import limiter
from utils.supabase_admin import get_public_user_by_identifier
from xera.user_auth import make_user_token

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_DUMMY_HASH = "$2b$12$KIXzCq3C3T6tFkUd9nj6aO.WwSIFqh4fQieFzpxKx5Mj5.z1rklHC"

class XeraLoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=512)

@router.post("/login")
@limiter.limit("10/minute")
async def xera_login(request: Request, data: XeraLoginRequest):
    user = await get_public_user_by_identifier(data.identifier.strip())
    stored_hash = user.get("password") if user else _DUMMY_HASH
    try:
        valid = pwd_context.verify(data.password, stored_hash)
    except Exception:
        valid = False
    if not user or not valid:
        raise HTTPException(status_code=401, detail="Invalid username/email or password.")
    if user.get("evoxera_status") and str(user.get("evoxera_status")).upper() not in {"ACTIVE", "VERIFIED"}:
        raise HTTPException(status_code=403, detail="This account is not active.")
    return {
        "status": "ok",
        "token": make_user_token(int(user["id"])),
        "user": {"id": user["id"], "username": user.get("username"), "email": user.get("email"), "full_name": user.get("full_name")},
    }
