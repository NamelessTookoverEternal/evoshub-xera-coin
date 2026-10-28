"""
EVOS Data Services — business logic and API routes, merged into the EVOS Hub backend.

This is the former evosdata/main.py. It is no longer a FastAPI application:
every `@app.<verb>` became `@router.<verb>` on the APIRouter below, which the Hub
mounts at /api/evosdata (see routes/evosdata.py). Route bodies, request/response
shapes, provider fallbacks, webhook idempotency and retry loops are unchanged.
Differences from the standalone app are limited to: shared limiter / Supabase
client, Hub-session authentication (see "HUB SESSION" below), environment
validation, and URLs that used to point at the standalone deployment.
"""
from fastapi import APIRouter, Request, HTTPException, Query, Depends, Header
from slowapi.util import get_remote_address

import os
import re
import base64
import requests
import hmac
import hashlib
from datetime import datetime, timedelta, timezone

from supabase import Client

from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional

from decimal import Decimal

from passlib.context import CryptContext

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import uuid
import asyncio
import httpx
import logging
import time
import threading

from utils.rate_limit import limiter          # the Hub's single shared limiter
from services.evosdata.db import get_supabase
from services.evosdata import datamart_stock

# =========================
# LOGGING
# =========================
logger = logging.getLogger(__name__)

# =========================
# ROUTER (mounted by the Hub at /api/evosdata)
# =========================
router = APIRouter()

# =========================
# ENV
# =========================
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY")

DATAMART_API_KEY = os.getenv("DATAMART_API_KEY")
DATAMART_WEBHOOK_SECRET = os.getenv("DATAMART_WEBHOOK_SECRET")
DATAMART_BASE = "https://api.datamartgh.shop/api/developer"

# DataMart caps real /verify-number checks at 2/minute per API key — that's a
# shared budget across every visitor on the site, not per-user. _verify_cache
# avoids repeat lookups for the same number (blur + submit re-check land the
# same result), and _verify_call_times paces us under DataMart's real cap so
# concurrent users degrade to "unknown" instead of hammering 429s.
_verify_cache = {}                # normalized phone -> (timestamp, result dict)
_verify_cache_lock = threading.Lock()
VERIFY_CACHE_TTL = 300             # seconds

_verify_call_times = []           # timestamps of real calls made to DataMart
_verify_call_lock = threading.Lock()
DATAMART_VERIFY_LIMIT = 2          # per DataMart docs
DATAMART_VERIFY_WINDOW = 60        # seconds


DATAMART_CHECKERS_BASE = "https://api.datamartgh.shop/api/checkers"
# Reuses DATAMART_API_KEY and DATAMART_WEBHOOK_SECRET — same account/wallet as data bundles,
# just a different base path per DataMart's docs.

CHECKER_PRICE_CACHE_TTL = 300
_checker_products_cache = {"data": None, "ts": 0}
_checker_products_lock = threading.Lock()

# Retail price shown to customers and charged at checkout, for every checker
# type (WAEC + BECE). Overrides whatever price DataMart reports on their
# /products endpoint — that field is still used for inStock/stockCount,
# just not for price. Change this single value to adjust pricing everywhere
# (customer purchase page, checkout total, and agent wallet debit).
CHECKER_SELL_PRICE = 18.50

# What an agent pays per card when buying a checker for a customer directly
# (agent_buy_checker) — this is the agent's cost, distinct from CHECKER_SELL_PRICE
# which is the customer-facing retail price. Also the floor for any per-agent
# resale markup set via /agent/checker-pricing — agents can only price at or
# above this, never below their own cost.
CHECKER_AGENT_BASE_PRICE = 16.80

BUNDLES_GHANA_API_KEY = os.getenv("BUNDLES_GHANA_API_KEY")
BUNDLES_GHANA_API_SECRET = os.getenv("BUNDLES_GHANA_API_SECRET")
# The Bundles Ghana proxy is a Netlify function (hub-frontend/netlify/functions/bundlesProxy.js).
# Override with BUNDLES_GHANA_BASE if it is hosted elsewhere.
BUNDLES_GHANA_BASE = os.getenv("BUNDLES_GHANA_BASE", "https://evoshub.xyz/.netlify/functions/bundlesProxy")
BUNDLES_PROXY_SECRET = os.getenv("BUNDLES_PROXY_SECRET", "")

MOOLRE_BASE = os.getenv("MOOLRE_BASE", "https://api.moolre.com/open/transact")
MOOLRE_USERNAME = os.getenv("MOOLRE_USERNAME")
MOOLRE_API_KEY = os.getenv("MOOLRE_API_KEY")
MOOLRE_ACCOUNT_NUMBER = os.getenv("MOOLRE_ACCOUNT_NUMBER")

SWIFT_DATA_LINK_API_KEY = os.getenv("SWIFT_DATA_LINK_API_KEY")
SWIFT_DATA_LINK_BASE    = os.getenv("SWIFT_DATA_LINK_BASE", "https://swiftdata-link.com/api/v1")
SWIFT_DATA_LINK_WEBHOOK = os.getenv("SWIFT_DATA_LINK_WEBHOOK_URL", os.getenv("HUB_API_PUBLIC_URL", "https://api.evoshub.xyz").rstrip("/") + "/api/evosdata/webhook/swiftdatalink")

AGYEKUMDATA_API_KEY          = os.getenv("AGYEKUMDATA_API_KEY")
AGYEKUMDATA_BASE             = os.getenv("AGYEKUMDATA_BASE", "https://www.agyekumdata.com/api/v1")
AGYEKUMDATA_WEBHOOK_SECRET   = os.getenv("AGYEKUMDATA_WEBHOOK_SECRET")

SMTP_HOST     = os.getenv("SMTP_HOST", "mail.spacemail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER     = os.getenv("SMTP_USER", "support@evoshub.xyz")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

ADMIN_SECRET = os.getenv("ADMIN_SECRET")

# =========================
# SAFETY CHECK
# =========================
required_envs = {
    "PAYSTACK_SECRET_KEY":        PAYSTACK_SECRET,
    "DATAMART_API_KEY":           DATAMART_API_KEY,
    "DATAMART_WEBHOOK_SECRET":    DATAMART_WEBHOOK_SECRET,
    "BUNDLES_GHANA_API_KEY":      BUNDLES_GHANA_API_KEY,
    "BUNDLES_GHANA_API_SECRET":   BUNDLES_GHANA_API_SECRET,
    "MOOLRE_USERNAME":            MOOLRE_USERNAME,
    "MOOLRE_API_KEY":             MOOLRE_API_KEY,
    "MOOLRE_ACCOUNT_NUMBER":      MOOLRE_ACCOUNT_NUMBER,
    "SWIFT_DATA_LINK_API_KEY":    SWIFT_DATA_LINK_API_KEY,
    "SWIFT_DATA_LINK_WEBHOOK":    SWIFT_DATA_LINK_WEBHOOK,
    "AGYEKUMDATA_API_KEY":        AGYEKUMDATA_API_KEY,
    "AGYEKUMDATA_WEBHOOK_SECRET": AGYEKUMDATA_WEBHOOK_SECRET,
    "ADMIN_SECRET":               ADMIN_SECRET,
    "SMTP_USER":                  SMTP_USER,
    "SMTP_PASSWORD":              SMTP_PASSWORD,
}

# Same fail-fast rule as the standalone app, but evaluated by the Hub at startup
# (routes/evosdata.py) so it can be switched off with EVOSDATA_ENABLED=false.
MISSING_ENVS = [k for k, v in required_envs.items() if not v]

# =========================
# SUPABASE INIT
# =========================
# Shares the Hub's service-role client (same Supabase project) unless
# EVOSDATA_SUPABASE_URL/EVOSDATA_SUPABASE_KEY are set. See services/evosdata/db.py.
supabase: Client = get_supabase()

# =========================
# GLOBAL TIMEOUT CONFIG
# =========================
REQUEST_TIMEOUT = 10
BG_TIMEOUT = 25

# =========================
# PHONE NORMALISATION
# =========================
PHONE_RE = re.compile(r"^\d{9,15}$")

def normalise_phone(raw: str) -> str:
    cleaned = re.sub(r"[\s\-\(\)]", "", raw.strip())
    if not PHONE_RE.match(cleaned):
        raise HTTPException(status_code=400, detail="Invalid phone number")
    return cleaned


# =========================
# PAYSTACK CALLBACK BASE (origin-aware)
# Customers who started a payment inside the Hub (evoshub.xyz/evosdata) are
# returned there; everyone else keeps the standalone evosdata.xyz behaviour.
# Only these two allowlisted bases can ever be chosen — the Origin header just
# selects between them, it is never echoed into the URL.
# =========================
_CALLBACK_BASES = {
    "https://evoshub.xyz":     "https://evoshub.xyz/evosdata",
    "https://www.evoshub.xyz": "https://evoshub.xyz/evosdata",
}
_DEFAULT_CALLBACK_BASE = "https://evosdata.xyz"

def callback_base(request: Request) -> str:
    origin = (request.headers.get("origin") or "").rstrip("/").lower()
    return _CALLBACK_BASES.get(origin, _DEFAULT_CALLBACK_BASE)

# =========================
# ADMIN AUTH DEPENDENCY
# =========================
def require_admin(request: Request):
    secret = request.headers.get("X-Admin-Secret", "")
    if not secret or not hmac.compare_digest(secret, ADMIN_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")

# =========================
# AGENT TOKEN AUTH
# =========================
def make_agent_token(agent_id: int) -> str:
    msg = str(agent_id).encode()
    sig = hmac.new(ADMIN_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    payload = base64.urlsafe_b64encode(msg).decode()
    return f"{payload}.{sig}"

# =========================
# HUB SESSION (central login)
# A valid EVOS Hub session token (the same signed token /api/xera/auth/login
# issues, verified server-side with XERA_TOKEN_SECRET) is accepted wherever an
# Evosdata user/agent token is. It only proves WHO the caller is: agent
# privileges are still read live from `users` (role + agent_status) on every
# agent request, so approval/revocation takes effect immediately, and a Hub
# token can never act for any user id other than its own.
# =========================
from xera.user_auth import XeraTokenInvalid, verify_user_token as _hub_verify_token

def _hub_session_uid(token: str):
    if not token:
        return None
    try:
        return int(_hub_verify_token(token))
    except (XeraTokenInvalid, RuntimeError, ValueError):
        return None

def _is_approved_agent(user_id: int) -> bool:
    try:
        res = supabase.table("users").select("role,agent_status").eq("id", user_id).limit(1).execute()
        row = (res.data or [None])[0]
        return bool(row) and row.get("role") == "agent" and row.get("agent_status") == "approved"
    except Exception as e:
        logger.error("HUB SESSION AGENT LOOKUP ERROR: %s", str(e))
        return False

def verify_agent_token(token: str, agent_id: int) -> bool:
    try:
        payload, sig = token.rsplit(".", 1)
        msg = base64.urlsafe_b64decode(payload.encode())
        expected_id = int(msg.decode())
        if expected_id != agent_id:
            return False
        expected_sig = hmac.new(ADMIN_SECRET.encode(), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        uid = _hub_session_uid(token)
        return uid is not None and uid == int(agent_id) and _is_approved_agent(uid)

def require_agent(request: Request, agent_id: int) -> int:
    token = request.headers.get("X-Agent-Token", "")
    if not token or not verify_agent_token(token, agent_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    return agent_id

# =========================
# USER TOKEN AUTH (every logged-in customer)
# =========================
# Signed with a different domain prefix ("user:") from the agent token, so a
# customer token can NEVER be replayed as an agent token on /agent/* routes.
# Carries an expiry. Used by /spin/* and /agent-fee/* (spin.py, agent_fee.py).
USER_TOKEN_TTL_SECONDS = 30 * 24 * 3600

def _user_token_sig(msg: bytes) -> str:
    return hmac.new(ADMIN_SECRET.encode(), b"user:" + msg, hashlib.sha256).hexdigest()

def make_user_token(user_id: int, ttl: int = USER_TOKEN_TTL_SECONDS) -> str:
    msg = f"{int(user_id)}:{int(time.time()) + ttl}".encode()
    return f"{base64.urlsafe_b64encode(msg).decode()}.{_user_token_sig(msg)}"

def verify_user_token(token: str, user_id: int) -> bool:
    try:
        payload, sig = token.rsplit(".", 1)
        msg = base64.urlsafe_b64decode(payload.encode())
        uid_s, exp_s = msg.decode().split(":", 1)
        if int(uid_s) != int(user_id) or int(exp_s) < time.time():
            return False
        return hmac.compare_digest(sig, _user_token_sig(msg))
    except Exception:
        uid = _hub_session_uid(token)
        return uid is not None and uid == int(user_id)

def require_user(request: Request, user_id: int) -> int:
    token = request.headers.get("X-User-Token", "")
    if not token or not verify_user_token(token, user_id):
        raise HTTPException(status_code=403, detail="Please sign in again")
    return int(user_id)

def resolve_order_identity(request: Request, claimed_user_id: Optional[int]) -> Optional[int]:
    """A client-supplied user_id is only a claim. A valid X-User-Token proves it
    (order attaches to the account); a wrong token is refused; no token means a
    guest purchase and the claim is dropped."""
    if not claimed_user_id:
        return None
    token = request.headers.get("X-User-Token", "")
    if not token:
        return None
    if not verify_user_token(token, claimed_user_id):
        raise HTTPException(status_code=403, detail="Please sign in again")
    return int(claimed_user_id)

# =========================
# MODELS
# =========================

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    full_name: str = Field(min_length=2, max_length=50)
    email: EmailStr
    phone: str = Field(min_length=9, max_length=15)
    password: str = Field(min_length=6, max_length=128)
    referred_by: Optional[str] = None

    @validator("username")
    def username_alphanumeric(cls, v):
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Username must be alphanumeric")
        return v.lower()

    @validator("phone")
    def phone_digits_only(cls, v):
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\d{9,15}$", cleaned):
            raise ValueError("Invalid phone number")
        return cleaned


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=128)


class CreateOrderRequest(BaseModel):
    user_id: Optional[int] = None
    network: str = Field(min_length=2, max_length=20)
    bundle: str = Field(min_length=2, max_length=20)
    phone: str = Field(min_length=9, max_length=15)
    email: Optional[EmailStr] = None

    @validator("network")
    def network_valid(cls, v):
        allowed = {"MTN", "TELECEL", "AIRTELTIGO", "AT"}
        if v.upper() not in allowed:
            raise ValueError("Invalid network")
        return v.upper()

    @validator("phone")
    def phone_clean(cls, v):
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\d{9,15}$", cleaned):
            raise ValueError("Invalid phone number")
        return cleaned


class VerifyNumberRequest(BaseModel):
    phoneNumber: str = Field(min_length=9, max_length=15)
    network: Optional[str] = None  # informational only — check is MTN-specific

    @validator("phoneNumber")
    def phone_clean(cls, v):
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\d{9,15}$", cleaned):
            raise ValueError("Invalid phone number")
        return cleaned


class AgentBuyDataRequest(BaseModel):
    agent_id: int
    network: str = Field(min_length=2, max_length=20)
    bundle: str = Field(min_length=2, max_length=20)
    phone_number: str = Field(min_length=9, max_length=15)

    @validator("network")
    def network_valid(cls, v):
        allowed = {"MTN", "TELECEL", "AIRTELTIGO", "AT"}
        if v.upper() not in allowed:
            raise ValueError("Invalid network")
        return v.upper()

    @validator("phone_number")
    def phone_clean(cls, v):
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\d{9,15}$", cleaned):
            raise ValueError("Invalid phone number")
        return cleaned


class StoreOrderRequest(BaseModel):
    agent_id: int
    network: str = Field(min_length=2, max_length=20)
    bundle: str = Field(min_length=2, max_length=20)
    phone_number: str = Field(min_length=9, max_length=15)
    email: Optional[EmailStr] = None

    @validator("network")
    def network_valid(cls, v):
        allowed = {"MTN", "TELECEL", "AIRTELTIGO", "AT"}
        if v.upper() not in allowed:
            raise ValueError("Invalid network")
        return v.upper()

    @validator("phone_number")
    def phone_clean(cls, v):
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\d{9,15}$", cleaned):
            raise ValueError("Invalid phone number")
        return cleaned


class CheckerStoreOrderRequest(BaseModel):
    agent_id: int
    checker_type: str = Field(min_length=3, max_length=10)
    phone_number: str = Field(min_length=9, max_length=15)
    quantity: int = Field(default=1, ge=1, le=20)
    email: Optional[EmailStr] = None

    @validator("checker_type")
    def checker_type_valid(cls, v):
        v = v.strip().upper()
        if v not in ("WAEC", "BECE"):
            raise ValueError("Invalid checker type")
        return v

    @validator("phone_number")
    def phone_clean(cls, v):
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\d{9,15}$", cleaned):
            raise ValueError("Invalid phone number")
        return cleaned


class DepositInitiateRequest(BaseModel):
    agent_id: int
    amount: float = Field(gt=0, le=10000)
    total_charge: float = Field(gt=0, le=11000)


class WithdrawRequest(BaseModel):
    agent_id: int
    amount: float = Field(gt=0, le=10000)
    mobile_number: str = Field(min_length=9, max_length=15)
    network: str = Field(min_length=2, max_length=20)
    account_name: Optional[str] = Field(default="", max_length=80)
    provider: str = Field(default="paystack")   # "paystack" or "moolre" — chosen on step 1

    @validator("mobile_number")
    def phone_clean(cls, v):
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\d{9,15}$", cleaned):
            raise ValueError("Invalid mobile number")
        return cleaned

    @validator("provider")
    def provider_valid(cls, v):
        v = (v or "paystack").strip().lower()
        if v not in ("paystack", "moolre"):
            raise ValueError("Invalid provider")
        return v


class VerifyAccountRequest(BaseModel):
    agent_id: int
    mobile_number: str = Field(min_length=9, max_length=15)
    network: str = Field(min_length=2, max_length=20)
    provider: str = Field(default="paystack")

    @validator("mobile_number")
    def phone_clean(cls, v):
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\d{9,15}$", cleaned):
            raise ValueError("Invalid mobile number")
        return cleaned

    @validator("provider")
    def provider_valid(cls, v):
        v = (v or "paystack").strip().lower()
        if v not in ("paystack", "moolre"):
            raise ValueError("Invalid provider")
        return v




class CreateCheckerOrderRequest(BaseModel):
    user_id: Optional[int] = None
    checker_type: str = Field(min_length=3, max_length=10)
    phone_number: str = Field(min_length=9, max_length=15)
    quantity: int = Field(default=1, ge=1, le=20)
    email: Optional[EmailStr] = None

    @validator("checker_type")
    def checker_type_valid(cls, v):
        v = v.strip().upper()
        if v not in ("WAEC", "BECE"):
            raise ValueError("Invalid checker type")
        return v

    @validator("phone_number")
    def phone_clean(cls, v):
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\d{9,15}$", cleaned):
            raise ValueError("Invalid phone number")
        return cleaned


class AgentBuyCheckerRequest(BaseModel):
    agent_id: int
    checker_type: str = Field(min_length=3, max_length=10)
    phone_number: str = Field(min_length=9, max_length=15)
    quantity: int = Field(default=1, ge=1, le=20)

    @validator("checker_type")
    def checker_type_valid(cls, v):
        v = v.strip().upper()
        if v not in ("WAEC", "BECE"):
            raise ValueError("Invalid checker type")
        return v

    @validator("phone_number")
    def phone_clean(cls, v):
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\d{9,15}$", cleaned):
            raise ValueError("Invalid phone number")
        return cleaned

# =========================
# HELPERS
# =========================

NETWORK_MAP = {
    "MTN": "YELLO",
    "TELECEL": "TELECEL",
    "AIRTELTIGO": "AT_PREMIUM"
}

MOOLRE_CHANNEL_MAP = {
    "MTN": 1,
    "TELECEL": 6,
    "AIRTELTIGO": 7,
}

PAYSTACK_MOMO_BANK_CODE = {
    "MTN": "MTN",
    "TELECEL": "VOD",       # confirmed via Paystack's Creating Transfer Recipients docs
    "AIRTELTIGO": "ATL",    # confirmed via the same docs
}

SDL_NETWORK_MAP = {
    "MTN":        "mtn",
    "TELECEL":    "telecel",
    "AIRTELTIGO": "at",
    "AT":         "at",
}

SDL_OFFER_SLUG = {
    "MTN":        "mtn_data_normal_delivery",
    "TELECEL":    "telecel_expiry_bundle",
    "AIRTELTIGO": "ishare_data_bundle",
    "AT":         "ishare_data_bundle",
}

# =========================
# AGYEKUMDATA CATEGORY MAP
# =========================
AGYEKUMDATA_CATEGORY_MAP = {
    "MTN":        "MTN Package",
    "TELECEL":    "Telecel Package",
    "AIRTELTIGO": "iShare package",
    "AT":         "iShare package",
}



# =========================
# DATAMART CHECKERS HELPERS
# Same X-API-Key, same wallet as data bundles — different base path.
# =========================

def _datamart_checkers_headers():
    return {"X-API-Key": DATAMART_API_KEY, "Content-Type": "application/json"}


def get_checker_products():
    """Cached product list — price + stock. TTL keeps us from hitting
    /api/checkers/products on every single page load."""
    now = time.time()
    with _checker_products_lock:
        if _checker_products_cache["data"] and now - _checker_products_cache["ts"] < CHECKER_PRICE_CACHE_TTL:
            return _checker_products_cache["data"]

    try:
        res = requests.get(
            f"{DATAMART_CHECKERS_BASE}/products",
            headers=_datamart_checkers_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        data = res.json().get("data", [])

        # Keep DataMart's stock info, but always sell at our own fixed price
        # rather than whatever they currently list.
        for p in data:
            if isinstance(p, dict):
                p["price"] = CHECKER_SELL_PRICE

        with _checker_products_lock:
            _checker_products_cache["data"] = data
            _checker_products_cache["ts"] = now
        return data
    except Exception as e:
        logger.error("CHECKER PRODUCTS ERROR: %s", str(e))
        with _checker_products_lock:
            return _checker_products_cache["data"] or []


def call_checker_purchase(checker_type: str, phone: str, ref: str, webhook_url: str = None, skip_sms: bool = False) -> dict:
    try:
        res = datamart_stock.purchase_post(
            f"{DATAMART_CHECKERS_BASE}/purchase",
            headers=_datamart_checkers_headers(),
            json={
                "checkerType": checker_type,
                "phoneNumber": phone,
                "ref": ref,
                "webhookUrl": webhook_url or "https://api.evosdata.xyz/webhook/datamart-checkers",
                "skipSms": skip_sms,
            },
            timeout=REQUEST_TIMEOUT,
        )
        return res.json()
    except Exception as e:
        logger.error("CHECKER PURCHASE ERROR: %s", str(e))
        return {"status": "error", "message": str(e)}


def call_checker_bulk_purchase(checker_type: str, phone: str, quantity: int, ref: str, webhook_url: str = None, skip_sms: bool = False) -> dict:
    try:
        res = datamart_stock.purchase_post(
            f"{DATAMART_CHECKERS_BASE}/bulk-purchase",
            headers=_datamart_checkers_headers(),
            json={
                "checkerType": checker_type,
                "phoneNumber": phone,
                "quantity": quantity,
                "ref": ref,
                "webhookUrl": webhook_url or "https://api.evosdata.xyz/webhook/datamart-checkers",
                "skipSms": skip_sms,
            },
            timeout=REQUEST_TIMEOUT,
        )
        return res.json()
    except Exception as e:
        logger.error("CHECKER BULK PURCHASE ERROR: %s", str(e))
        return {"status": "error", "message": str(e)}


def call_checker_order_status(reference: str) -> dict:
    try:
        res = requests.get(
            f"{DATAMART_CHECKERS_BASE}/order-status/{reference}",
            headers=_datamart_checkers_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        return res.json()
    except Exception as e:
        logger.error("CHECKER STATUS ERROR: %s", str(e))
        return {"status": "error", "message": str(e)}


def sanitise_checker_ref(ref: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\-_]", "", ref)
    return cleaned[:40]


def dispatch_checker_order(checker: dict):
    """Called once payment is confirmed (webhook or retry job). Buys the
    card(s) from DataMart and stores serial/pin. Raises on failure so the
    caller can decide how to mark the row."""
    checker_id   = checker["id"]
    checker_type = checker["checker_type"]
    phone        = checker["phone_number"]
    quantity     = checker.get("quantity", 1)
    raw_ref      = checker.get("evosdata_ref") or checker.get("paystack_ref") or str(checker_id)
    safe_ref     = sanitise_checker_ref(raw_ref)

    if quantity > 1:
        result = call_checker_bulk_purchase(checker_type, phone, quantity, safe_ref)
        if result.get("status") != "success":
            raise Exception(f"Bulk checker purchase failed: {result.get('message', result)}")
        data  = result.get("data", {})
        cards = data.get("cards", [])
        supabase.table("checkers").update({
            "status":               "successful",
            "datamart_ref":         safe_ref,
            "serial_numbers":       cards,
        }).eq("id", checker_id).execute()
        logger.info("CHECKER DISPATCH: order %s bulk-purchased %d %s cards ✅", checker_id, quantity, checker_type)
        try:
            process_checker_agent_profit(checker_id, safe_ref)
        except Exception as profit_err:
            logger.error("CHECKER AGENT PROFIT ERROR (bulk): %s", str(profit_err))

    else:
        result = call_checker_purchase(checker_type, phone, safe_ref)
        if result.get("status") != "success":
            raise Exception(f"Checker purchase failed: {result.get('message', result)}")
        data = result.get("data", {})
        card = {
            "purchaseId":   data.get("purchaseId"),
            "reference":    data.get("reference"),
            "serialNumber": data.get("serialNumber"),
            "pin":          data.get("pin"),
            "price":        data.get("price"),
            "createdAt":    data.get("createdAt"),
        }
        supabase.table("checkers").update({
            "status":               "successful",
            "datamart_ref":         data.get("reference") or safe_ref,
            "datamart_purchase_id": data.get("purchaseId"),
            "serial_numbers":       [card],
        }).eq("id", checker_id).execute()
        logger.info("CHECKER DISPATCH: order %s purchased %s card ✅", checker_id, checker_type)
        try:
            process_checker_agent_profit(checker_id, data.get("reference") or safe_ref)
        except Exception as profit_err:
            logger.error("CHECKER AGENT PROFIT ERROR (single): %s", str(profit_err))


# =========================
# RETRY ESCALATION CONFIG
# FIX: orders no longer hammer a single provider forever. Each order tracks
#      retry_attempts (tries on its CURRENT provider) and provider_priority
#      (which tier of the network's provider chain it's currently on).
#      After MAX_ATTEMPTS_PER_PROVIDER failed tries, the order escalates to
#      the next-priority active provider for that network. Only once every
#      provider in the chain has been exhausted AND the order is >= 3h old
#      does it get marked "failed".
#
#      Requires these columns on the "orders" table (run once in Supabase):
#        alter table orders add column if not exists retry_attempts int default 0;
#        alter table orders add column if not exists provider_priority int default 1;
# =========================
MAX_ATTEMPTS_PER_PROVIDER = 3

# =========================
# WITHDRAWAL LIQUIDITY FEE
# A flat 4% liquidity fee is charged on every agent withdrawal. The agent's
# wallet is debited the FULL amount they typed (e.g. GH₵100), but only the
# amount after the fee is actually sent out (e.g. GH₵96). The fee itself
# stays with the business.
#
#   fee           = amount * WITHDRAWAL_FEE_PERCENT / 100
#   payout_amount = amount - fee   (this is what actually gets transferred)
#
#      Requires these columns on the "agent_withdrawals" table (run once in
#      Supabase):
#        alter table agent_withdrawals add column if not exists fee numeric default 0;
#        alter table agent_withdrawals add column if not exists payout_amount numeric default 0;
#        alter table agent_withdrawals add column if not exists failure_reason text;
#      "failure_reason" holds the internal (never agent-facing) reason a
#      transfer couldn't be completed — e.g. "business balance too low" or
#      "auto-refunded after 60 min". Used by admin tooling and the
#      background retry job; never returned to the agent.
# =========================
WITHDRAWAL_FEE_PERCENT = 4.0

def calc_withdrawal_fee(amount: float):
    fee = round(float(amount) * (WITHDRAWAL_FEE_PERCENT / 100), 2)
    payout_amount = round(float(amount) - fee, 2)
    return fee, payout_amount

# =========================
# BUNDLES GHANA HELPER
# =========================
def call_bundles_ghana(endpoint: str, method: str = "GET", body: dict = None):
    if not endpoint or not isinstance(endpoint, str):
        raise Exception(f"Invalid Bundles Ghana endpoint: {endpoint}")
    try:
        logger.info("CALLING BG PATH: %s METHOD: %s", endpoint, method)
        res = requests.post(
            BUNDLES_GHANA_BASE,
            json={"path": endpoint, "method": method, "body": body},
            headers={"X-Proxy-Secret": BUNDLES_PROXY_SECRET} if BUNDLES_PROXY_SECRET else None,
            timeout=BG_TIMEOUT
        )
        return res.json()
    except Exception as e:
        logger.error("BUNDLES GHANA PROXY ERROR: %s", str(e))
        return {"success": False, "error": str(e)}


# =========================
# SWIFT DATA LINK HELPER
# =========================
def call_swift_data_link(network: str, volume: float, phone: str) -> dict:
    network_slug = SDL_NETWORK_MAP.get(network.upper())
    offer_slug   = SDL_OFFER_SLUG.get(network.upper())

    if not network_slug or not offer_slug:
        return {"success": False, "error": f"Unsupported network: {network}"}

    phone = phone.strip()
    if phone.startswith("0"):
        phone = "233" + phone[1:]
    elif not phone.startswith("233"):
        phone = "233" + phone

    try:
        res = requests.post(
            f"{SWIFT_DATA_LINK_BASE}/order/{network_slug}",
            headers={"x-api-key": SWIFT_DATA_LINK_API_KEY, "Content-Type": "application/json"},
            json={
                "type":       "single",
                "volume":     int(volume),
                "phone":      phone,
                "offerSlug":  offer_slug,
                "webhookUrl": SWIFT_DATA_LINK_WEBHOOK,
            },
            timeout=REQUEST_TIMEOUT
        )
        return res.json()
    except Exception as e:
        logger.error("SDL ORDER ERROR: %s", str(e))
        return {"success": False, "error": str(e)}


# =========================
# AGYEKUMDATA HELPERS
# =========================

def _agyekumdata_headers():
    return {
        "X-API-KEY": AGYEKUMDATA_API_KEY,
        "Content-Type": "application/json"
    }

def _safe_agyekumdata_json(res: requests.Response, context: str) -> dict:
    logger.info(
        "AGYEKUMDATA %s RAW: status=%s body=%s",
        context, res.status_code, res.text[:500]
    )
    if not res.text or not res.text.strip():
        return {"success": False, "error": f"Empty response (HTTP {res.status_code})"}
    try:
        return res.json()
    except ValueError as e:
        logger.error("AGYEKUMDATA %s JSON ERROR: %s | body was: %s", context, str(e), res.text[:200])
        return {"success": False, "error": f"Invalid JSON: {str(e)}"}


def sanitise_agyekumdata_ref(ref: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9_]", "", ref.upper())
    return cleaned[:20]


def get_agyekumdata_package_id(network: str, bundle: str) -> str:
    category = AGYEKUMDATA_CATEGORY_MAP.get(network.upper(), network)
    bundle_clean = bundle.strip().upper().replace(" ", "")
    fallback = f"{category}-{bundle_clean}"

    try:
        res = requests.get(
            f"{AGYEKUMDATA_BASE}/products",
            headers=_agyekumdata_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        data = _safe_agyekumdata_json(res, "PRODUCTS")
        products = data if isinstance(data, list) else data.get("data", [])

        category_products = [
            p for p in products
            if p.get("category", "").strip() == category
        ]

        for product in category_products:
            title_clean = product.get("title", "").upper().replace(" ", "")
            if title_clean == bundle_clean:
                package_id = product.get("packageid") or product.get("packageId")
                if package_id:
                    logger.info(
                        "AGYEKUMDATA PRODUCTS: matched packageId=%s category=%s",
                        package_id, category
                    )
                    return package_id

        logger.warning(
            "AGYEKUMDATA PRODUCTS: no match for %s %s in category=%s fallback=%s",
            network, bundle, category, fallback
        )
        return fallback

    except Exception as e:
        logger.error("AGYEKUMDATA PRODUCTS ERROR: %s", str(e))
        return fallback


def call_agyekumdata_purchase(package_id: str, phone: str, client_reference: str) -> dict:
    phone = phone.strip()

    if phone.startswith("233") and len(phone) == 12:
        phone = "0" + phone[3:]
    elif len(phone) == 9 and not phone.startswith("0"):
        phone = "0" + phone

    safe_ref = sanitise_agyekumdata_ref(client_reference)

    body = {
        "packageId": package_id,
        "mobileNo": phone,
        "clientReference": safe_ref,
    }

    url = f"{AGYEKUMDATA_BASE}/purchase"

    logger.info("AGYEKUMDATA PURCHASE URL: %s", url)
    logger.info(
        "AGYEKUMDATA PURCHASE: packageId=%s phone=%s ref=%s",
        package_id, phone, safe_ref
    )

    try:
        res = requests.post(
            url,
            headers=_agyekumdata_headers(),
            json=body,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )

        if res.status_code in (301, 302, 307, 308):
            location = res.headers.get("Location")
            logger.error("AGYEKUMDATA REDIRECT: %s -> %s", res.status_code, location)
            return {"success": False, "error": f"API redirected to {location}"}

        result = _safe_agyekumdata_json(res, "PURCHASE")

        if not result.get("success"):
            logger.error(
                "AGYEKUMDATA PURCHASE FAILED: status=%s error=%s message=%s",
                res.status_code, result.get("error"), result.get("message")
            )

        return result

    except requests.exceptions.Timeout:
        logger.error("AGYEKUMDATA PURCHASE TIMEOUT ref=%s", safe_ref)
        return {"success": False, "error": "Request timed out"}

    except requests.exceptions.ConnectionError as e:
        logger.error("AGYEKUMDATA CONNECTION ERROR: %s", str(e))
        return {"success": False, "error": str(e)}

    except Exception as e:
        logger.error("AGYEKUMDATA PURCHASE ERROR: %s", str(e))
        return {"success": False, "error": str(e)}


def call_agyekumdata_status(client_reference: str) -> dict:
    safe_ref = sanitise_agyekumdata_ref(client_reference)

    try:
        res = requests.get(
            f"{AGYEKUMDATA_BASE}/order/status",
            headers=_agyekumdata_headers(),
            params={"clientReference": safe_ref},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False
        )

        if "text/html" in res.headers.get("Content-Type", "") or res.text.strip().startswith("<!DOCTYPE"):
            logger.error(
                "AGYEKUMDATA STATUS HTML RESPONSE (likely auth/base URL issue): %s",
                res.text[:200]
            )
            return {"success": False, "error": "Invalid API response (HTML instead of JSON)"}

        return _safe_agyekumdata_json(res, "STATUS")

    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}

    except Exception as e:
        logger.error("AGYEKUMDATA STATUS ERROR: %s", str(e))
        return {"success": False, "error": str(e)}


def log_agyekumdata_categories():
    try:
        res = requests.get(
            f"{AGYEKUMDATA_BASE}/categories",
            headers=_agyekumdata_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        data = _safe_agyekumdata_json(res, "CATEGORIES")
        logger.info("AGYEKUMDATA CATEGORIES: %s", data)
        return data
    except Exception as e:
        logger.error("AGYEKUMDATA CATEGORIES ERROR: %s", str(e))
        return {"success": False, "error": str(e)}


def verify_agyekumdata_signature(body: bytes, signature: str) -> bool:
    try:
        if not signature:
            logger.warning("AGYEKUMDATA WEBHOOK: missing signature")
            return False
        computed = hmac.new(
            AGYEKUMDATA_WEBHOOK_SECRET.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(computed, signature)
    except Exception as e:
        logger.error("AGYEKUMDATA SIGNATURE ERROR: %s", str(e))
        return False


# =========================
# MOOLRE HELPER
# =========================
def call_moolre(endpoint: str, body: dict):
    try:
        res = requests.post(
            f"{MOOLRE_BASE}/{endpoint}",
            headers={
                "X-API-USER": MOOLRE_USERNAME,
                "X-API-KEY": MOOLRE_API_KEY,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=REQUEST_TIMEOUT
        )
        return res.json()
    except Exception as e:
        logger.error("MOOLRE ERROR: %s", str(e))
        return {"status": 0, "message": str(e)}


# =========================
# PAYSTACK TRANSFER HELPERS
# =========================
# =========================
# PAYSTACK ACCOUNT RESOLUTION
# Per Paystack's docs, /transferrecipient does NOT reliably return a resolved
# account_name for mobile money in `data.details` — name resolution is a
# separate call: GET /bank/resolve?account_number=...&bank_code=...
# This must run BEFORE recipient creation if you want the real account name
# instead of "Not verified".
#
# NOTE: Resolve Account Number is documented as available for Ghana, but in
# practice its coverage per mobile-money network is uneven — MTN tends to
# resolve reliably, while Telecel/AirtelTigo often come back with
# status:false and no usable name for a given number. That's a Paystack-side
# data-coverage limitation, not a request-shape bug, so we log the raw
# response and surface the reason instead of silently swallowing it.
# =========================
def paystack_resolve_account(account_number: str, bank_code: str) -> dict:
    try:
        res = requests.get(
            "https://api.paystack.co/bank/resolve",
            params={"account_number": account_number, "bank_code": bank_code},
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"},
            timeout=REQUEST_TIMEOUT,
        )
        data = res.json()
        logger.info(
            "PAYSTACK RESOLVE: bank_code=%s account=%s http=%s status=%s message=%s",
            bank_code, account_number, res.status_code, data.get("status"), data.get("message")
        )
        return data
    except Exception as e:
        logger.error("PAYSTACK RESOLVE ACCOUNT ERROR: %s", str(e))
        return {"status": False, "message": str(e)}


def paystack_create_recipient(name: str, mobile_number: str, network: str) -> dict:
    bank_code = PAYSTACK_MOMO_BANK_CODE.get(network.upper())
    if not bank_code:
        return {"status": False, "message": f"Unsupported network for Paystack transfer: {network}"}
    try:
        res = requests.post(
            "https://api.paystack.co/transferrecipient",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
            json={
                "type": "mobile_money",
                "name": name or "EVOS Agent",
                "account_number": mobile_number,
                "bank_code": bank_code,
                "currency": "GHS",
            },
            timeout=REQUEST_TIMEOUT,
        )
        return res.json()
    except Exception as e:
        logger.error("PAYSTACK RECIPIENT ERROR: %s", str(e))
        return {"status": False, "message": str(e)}


def paystack_initiate_transfer(amount: float, recipient_code: str, reference: str, reason: str) -> dict:
    try:
        res = requests.post(
            "https://api.paystack.co/transfer",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
            json={
                "source": "balance",
                "amount": int(round(amount * 100)),
                "recipient": recipient_code,
                "reference": reference,
                "reason": reason,
                "currency": "GHS",
            },
            timeout=REQUEST_TIMEOUT,
        )
        return res.json()
    except Exception as e:
        logger.error("PAYSTACK TRANSFER ERROR: %s", str(e))
        return {"status": False, "message": str(e)}


def paystack_verify_transfer(reference: str) -> dict:
    try:
        res = requests.get(
            f"https://api.paystack.co/transfer/verify/{reference}",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"},
            timeout=REQUEST_TIMEOUT,
        )
        return res.json()
    except Exception as e:
        logger.error("PAYSTACK VERIFY TRANSFER ERROR: %s", str(e))
        return {"status": False, "message": str(e)}


# =========================
# WITHDRAWAL FINALIZATION (shared, atomic)
# Every path that can resolve a "processing" paystack withdrawal — the
# webhook, the agent's status-poll endpoint, the background retry job, and
# admin actions — funnels through here. The atomic
# `.eq("status", "processing")` guard on the update means only ONE caller
# can ever win the transition for a given withdrawal, no matter how many of
# these fire concurrently. That's what prevents double-crediting the agent's
# wallet on a refund, or double-inserting the debit transaction on a payout.
# Requires the "failure_reason" column (see migration note below).
# =========================
def finalize_paystack_withdrawal(row: dict, final_status: str, note: str = None) -> bool:
    if final_status not in ("paid", "failed"):
        return False

    withdrawal_id = row["id"]
    agent_id      = row["agent_id"]
    amount        = float(row["amount"])
    reference     = row.get("paystack_ref")

    update_payload = {"status": final_status}
    if note:
        update_payload["failure_reason"] = note

    claim = supabase.table("agent_withdrawals") \
        .update(update_payload) \
        .eq("id", withdrawal_id) \
        .eq("status", "processing") \
        .execute()

    if not claim.data:
        # Someone else (webhook / poll / retry job / admin) already
        # finalized this withdrawal — nothing more to do here.
        return False

    if final_status == "paid":
        existing_tx = supabase.table("agent_transactions").select("id").eq("reference", reference).limit(1).execute()
        if not existing_tx.data:
            supabase.table("agent_transactions").insert({
                "agent_id":  agent_id,
                "amount":    -amount,
                "type":      "withdrawal",
                "reference": reference,
            }).execute()
        logger.info("WITHDRAWAL FINALIZE: withdrawal %s marked paid", withdrawal_id)
    else:
        wlt = supabase.table("agent_wallets").select("balance").eq("agent_id", agent_id).limit(1).execute()
        if wlt.data:
            new_balance = round(float(wlt.data[0]["balance"]) + amount, 2)
            supabase.table("agent_wallets").update({"balance": new_balance}).eq("agent_id", agent_id).execute()
            logger.info(
                "WITHDRAWAL FINALIZE: refunded GH₵%s to agent %s (withdrawal %s) — reason: %s",
                amount, agent_id, withdrawal_id, note or "unspecified"
            )
        else:
            logger.error(
                "WITHDRAWAL FINALIZE: no wallet found for agent %s — could not refund withdrawal %s!",
                agent_id, withdrawal_id
            )

    return True


# =========================
# PASSWORD SECURITY
# =========================
pwd_context = CryptContext(
    schemes=["bcrypt"],
    bcrypt__rounds=12,
    deprecated="auto"
)

def hash_password(password: str) -> str:
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.error("HASH ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Password hashing failed")

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception as e:
        logger.error("VERIFY ERROR: %s", str(e))
        return False


# =========================
# UTILITIES
# =========================
def extract_capacity(bundle: str) -> str:
    if not bundle:
        return ""
    return bundle.upper().replace("GB", "").replace("MB", "").strip()

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def parse_db_dt(raw: str) -> datetime:
    if not raw:
        raise ValueError("Empty datetime string")
    cleaned = raw.replace("Z", "").replace("+00:00", "")
    naive = datetime.fromisoformat(cleaned)
    return naive.replace(tzinfo=timezone.utc)


# =========================
# PAYSTACK SIGNATURE (SHA512)
# =========================
def verify_paystack_signature(body: bytes, signature: str, secret: str) -> bool:
    try:
        if not signature:
            logger.warning("PAYSTACK SIGNATURE ERROR: missing signature")
            return False
        computed = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha512
        ).hexdigest()
        return hmac.compare_digest(computed, signature)
    except Exception as e:
        logger.error("PAYSTACK SIGNATURE ERROR: %s", str(e))
        return False


# =========================
# DATAMART SIGNATURE (SHA256)
# =========================
def verify_datamart_signature(body: bytes, signature: str, secret: str) -> bool:
    try:
        if not signature:
            logger.warning("DATAMART SIGNATURE ERROR: missing signature")
            return False
        computed = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(computed, signature)
    except Exception as e:
        logger.error("DATAMART SIGNATURE ERROR: %s", str(e))
        return False

def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    return verify_paystack_signature(body, signature, secret)


# =========================
# NETWORK PROVIDERS
# =========================
def get_provider(network: str):
    """Single highest-priority active provider — used for first dispatch
    (webhook handlers, agent buy-data, store orders), not for the retry loop."""
    try:
        res = supabase.table("provider_routes") \
            .select("provider") \
            .eq("network", network.upper()) \
            .eq("active", True) \
            .order("priority") \
            .limit(1) \
            .execute()
        if res.data:
            return res.data[0]["provider"]
        return None
    except Exception as e:
        logger.error("PROVIDER LOOKUP ERROR: %s", str(e))
        return None


def get_provider_chain(network: str):
    """Return ALL active providers for a network, ordered by priority asc.
    Used by the retry job so it can escalate through providers in order."""
    try:
        res = supabase.table("provider_routes") \
            .select("provider") \
            .eq("network", network.upper()) \
            .eq("active", True) \
            .order("priority") \
            .execute()
        return [r["provider"] for r in (res.data or [])]
    except Exception as e:
        logger.error("PROVIDER CHAIN ERROR: %s", str(e))
        return []


def handle_provider_failure(order: dict, chain: list, current_idx: int, provider: str, reason):
    """
    Called whenever a provider rejects an order during the retry job.
    Escalates to the next provider in the chain after MAX_ATTEMPTS_PER_PROVIDER
    failed tries on the current one, instead of retrying the same provider
    forever. Only fails the order outright once every provider in the chain
    has been exhausted AND the order is at least 3 hours old.
    """
    attempts = int(order.get("retry_attempts") or 0) + 1
    order_id = order["id"]

    if attempts < MAX_ATTEMPTS_PER_PROVIDER:
        supabase.table("orders").update({"retry_attempts": attempts}).eq("id", order_id).execute()
        logger.warning(
            "RETRY JOB: order %s attempt %d/%d on %s failed (%s) — will retry same provider next cycle",
            order_id, attempts, MAX_ATTEMPTS_PER_PROVIDER, provider, reason
        )
        return

    next_idx = current_idx + 1
    if next_idx < len(chain):
        supabase.table("orders").update({
            "provider_priority": next_idx + 1,  # stored 1-indexed
            "retry_attempts": 0
        }).eq("id", order_id).execute()
        logger.warning(
            "RETRY JOB: order %s exhausted %s after %d attempts (%s) — escalating to %s",
            order_id, provider, attempts, reason, chain[next_idx]
        )
        return

    # All providers in the chain have been exhausted
    order_age = utc_now() - parse_db_dt(order["created_at"])
    if order_age >= timedelta(hours=3):
        supabase.table("orders").update({"status": "failed"}).eq("id", order_id).execute()
        logger.error(
            "RETRY JOB: order %s FAILED — exhausted all %d provider(s) in chain, age %s >= 3h",
            order_id, len(chain), str(order_age).split('.')[0]
        )
    else:
        supabase.table("orders").update({"retry_attempts": attempts}).eq("id", order_id).execute()
        logger.warning(
            "RETRY JOB: order %s exhausted all providers, age %s < 3h — retrying last provider (%s)",
            order_id, str(order_age).split('.')[0], provider
        )


# =========================
# AGENT PROFIT
# =========================
def process_agent_profit(order_id, reference):
    existing = supabase.table("agent_transactions") \
        .select("id") \
        .eq("reference", reference) \
        .limit(1) \
        .execute()
    if existing.data:
        return

    order_res = supabase.table("orders") \
        .select("*") \
        .eq("id", order_id) \
        .limit(1) \
        .execute()
    if not order_res.data:
        return

    order = order_res.data[0]
    agent_id    = order.get("agent_id")
    base_price  = order.get("base_price")
    agent_price = order.get("agent_price")

    if not agent_id or base_price is None or agent_price is None:
        return

    profit = Decimal(str(agent_price)) - Decimal(str(base_price))
    if profit <= 0:
        return

    wallet = supabase.table("agent_wallets") \
        .select("*") \
        .eq("agent_id", agent_id) \
        .limit(1) \
        .execute()

    if wallet.data:
        new_balance = Decimal(str(wallet.data[0]["balance"])) + profit
        supabase.table("agent_wallets") \
            .update({"balance": float(new_balance)}) \
            .eq("agent_id", agent_id) \
            .execute()
    else:
        supabase.table("agent_wallets") \
            .insert({"agent_id": agent_id, "balance": float(profit)}) \
            .execute()

    supabase.table("agent_transactions").insert({
        "agent_id":  agent_id,
        "order_id":  order_id,
        "amount":    float(profit),
        "type":      "credit",
        "reference": reference
    }).execute()


def process_checker_agent_profit(checker_id, reference):
    """Mirrors process_agent_profit but for the checkers table. Only fires
    for store-checkout rows (base_price + agent_price populated) — direct
    customer purchases and an agent's own agent/buy-checker purchases leave
    those columns empty, so this is a no-op for them."""
    existing = supabase.table("agent_transactions") \
        .select("id") \
        .eq("reference", reference) \
        .limit(1) \
        .execute()
    if existing.data:
        return

    checker_res = supabase.table("checkers") \
        .select("*") \
        .eq("id", checker_id) \
        .limit(1) \
        .execute()
    if not checker_res.data:
        return

    checker = checker_res.data[0]
    agent_id    = checker.get("agent_id")
    base_price  = checker.get("base_price")
    agent_price = checker.get("agent_price")

    if not agent_id or base_price is None or agent_price is None:
        return

    profit = Decimal(str(agent_price)) - Decimal(str(base_price))
    if profit <= 0:
        return

    wallet = supabase.table("agent_wallets") \
        .select("*") \
        .eq("agent_id", agent_id) \
        .limit(1) \
        .execute()

    if wallet.data:
        new_balance = Decimal(str(wallet.data[0]["balance"])) + profit
        supabase.table("agent_wallets") \
            .update({"balance": float(new_balance)}) \
            .eq("agent_id", agent_id) \
            .execute()
    else:
        supabase.table("agent_wallets") \
            .insert({"agent_id": agent_id, "balance": float(profit)}) \
            .execute()

    supabase.table("agent_transactions").insert({
        "agent_id":  agent_id,
        "order_id":  checker_id,
        "amount":    float(profit),
        "type":      "credit",
        "reference": reference
    }).execute()


# =========================
# USER STATS
# =========================
def calculate_rank(order_count: int):
    if order_count >= 50:   return 5
    elif order_count >= 20: return 4
    elif order_count >= 10: return 3
    elif order_count >= 5:  return 2
    return 1

def increment_user_orders(user_id: int):
    try:
        user = supabase.table("users").select("order_count").eq("id", user_id).limit(1).execute()
        if not user.data:
            return
        current = user.data[0].get("order_count") or 0
        new_count = current + 1
        supabase.table("users").update({
            "order_count": new_count,
            "rank": calculate_rank(new_count)
        }).eq("id", user_id).execute()
    except Exception as e:
        logger.error("INCREMENT USER ERROR: %s", str(e))


# =========================
# PRICES
# =========================
@router.get("/prices")
@limiter.limit("60/minute")
def get_prices(request: Request):
    try:
        data = supabase.table("prices").select("*").execute().data or []
        try:
            datamart_stock.annotate(data)   # adds in_stock to every bundle
        except Exception as stock_err:
            logger.warning("PRICES: stock annotate skipped (%s)", stock_err)
        return {"status": "success", "data": data}
    except Exception as e:
        logger.error("PRICES ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to load prices")



# =========================
# CHECKERS: PRODUCTS (proxy — frontend never sees the DataMart API key)
# =========================
@router.get("/checkers/products")
@limiter.limit("60/minute")
def list_checker_products(request: Request):
    try:
        products = get_checker_products()
        return {"status": "success", "data": products}
    except Exception as e:
        logger.error("CHECKER PRODUCTS PROXY ERROR: %s", str(e))
        return {"status": "error", "data": []}


@router.post("/checkers/create")
@limiter.limit("10/minute")
def create_checker_order(request: Request, data: CreateCheckerOrderRequest):
    try:
        data.user_id = resolve_order_identity(request, data.user_id)
        products = get_checker_products()
        product = next((p for p in products if p.get("name", "").upper() == data.checker_type), None)
        if not product:
            raise HTTPException(400, "Checker type not available")
        if not product.get("inStock"):
            raise HTTPException(400, f"{data.checker_type} checkers are currently out of stock")

        unit_price = float(product.get("price", 0))
        if unit_price <= 0:
            raise HTTPException(400, "Invalid checker price")

        total_price = round(unit_price * data.quantity, 2)

        customer_email = None
        if data.user_id:
            user_res = supabase.table("users").select("email").eq("id", data.user_id).limit(1).execute()
            if not user_res.data:
                raise HTTPException(404, "User not found")
            customer_email = user_res.data[0]["email"]
        else:
            customer_email = data.email or "guest@evoshub.com"

        try:
            paystack = requests.post(
                "https://api.paystack.co/transaction/initialize",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
                json={
                    "email": customer_email,
                    "amount": int(total_price * 100),
                    "callback_url": f"{callback_base(request)}/success?type=checker",
                },
                timeout=REQUEST_TIMEOUT,
            ).json()
        except requests.exceptions.RequestException:
            raise HTTPException(500, "Payment service error")

        if not paystack.get("status"):
            raise HTTPException(400, "Payment init failed")

        ref      = paystack["data"]["reference"]
        evos_ref = f"CHK-{uuid.uuid4().hex[:8].upper()}"

        supabase.table("checkers").insert({
            "user_id":      data.user_id,
            "guest_email":  None if data.user_id else customer_email,
            "checker_type": data.checker_type,
            "phone_number": data.phone_number,
            "quantity":     data.quantity,
            "price":        total_price,
            "paystack_ref": ref,
            "evosdata_ref": evos_ref,
            "status":       "pending_payment",
        }).execute()

        return {"status": True, "payment_url": paystack["data"]["authorization_url"], "reference": ref}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("CREATE CHECKER ORDER ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Server error")


# =========================
# CHECKERS: STATUS (by Paystack reference — used by Success.jsx)
# If the webhook hasn't landed yet when the customer bounces back from
# Paystack, this verifies + dispatches inline instead of making them wait
# for the 5-minute retry_stuck_checker_payments cycle.
# =========================
@router.get("/checkers/status/{reference}")
@limiter.limit("20/minute")
async def get_checker_status(request: Request, reference: str):
    try:
        res = supabase.table("checkers").select("*").eq("paystack_ref", reference).limit(1).execute()
        if not res.data:
            raise HTTPException(404, "Checker order not found")
        checker = res.data[0]

        if checker["status"] in ("pending_payment", "failed") and not checker.get("datamart_ref"):
            try:
                async with httpx.AsyncClient() as client:
                    pres = await client.get(
                        f"https://api.paystack.co/transaction/verify/{reference}",
                        headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"},
                        timeout=15,
                    )
                    pdata = pres.json()

                if pdata.get("data", {}).get("status") == "success":
                    recheck = supabase.table("checkers").select("*").eq("id", checker["id"]).limit(1).execute()
                    fresh = recheck.data[0] if recheck.data else checker
                    if fresh["status"] in ("pending_payment", "failed") and not fresh.get("datamart_ref"):
                        supabase.table("checkers").update({"status": "paid"}).eq("id", checker["id"]).execute()
                        fresh_paid = supabase.table("checkers").select("*").eq("id", checker["id"]).limit(1).execute().data[0]
                        try:
                            dispatch_checker_order(fresh_paid)
                        except Exception as dispatch_err:
                            logger.error("CHECKER STATUS: dispatch error for checker %s: %s", checker["id"], str(dispatch_err))
                            supabase.table("checkers").update({"status": "failed"}).eq("id", checker["id"]).execute()
                    # re-fetch once more so the response reflects the dispatch outcome
                    checker = supabase.table("checkers").select("*").eq("id", checker["id"]).limit(1).execute().data[0]
            except Exception as verify_err:
                logger.error("CHECKER STATUS: verify error for ref %s: %s", reference, str(verify_err))

        return {
            "status":         checker["status"],
            "checker_type":   checker["checker_type"],
            "quantity":       checker["quantity"],
            "phone_number":   checker["phone_number"],
            "price":          checker["price"],
            "serial_numbers": checker.get("serial_numbers") or [],
            "reference":      checker["paystack_ref"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("CHECKER STATUS ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch checker status")


# =========================
# CHECKERS: TRACK (by phone — mirrors /orders/track)
# =========================
@router.get("/checkers/track")
@limiter.limit("20/minute")
def track_checkers(request: Request, phone: str = Query(...)):
    try:
        cleaned = normalise_phone(phone)
        res = supabase.table("checkers") \
            .select("checker_type, quantity, price, phone_number, status, created_at, evosdata_ref, paystack_ref, serial_numbers") \
            .eq("phone_number", cleaned) \
            .order("created_at", desc=True) \
            .limit(10) \
            .execute()
        return {"checkers": res.data or []}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("CHECKER TRACK ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch checker orders")


@router.post("/agent/buy-checker")
@limiter.limit("10/minute")
async def agent_buy_checker(request: Request, payload: AgentBuyCheckerRequest):
    try:
        token = request.headers.get("X-Agent-Token", "")
        if not token or not verify_agent_token(token, payload.agent_id):
            raise HTTPException(status_code=403, detail="Forbidden")

        agent_id = payload.agent_id

        agent_res = supabase.table("users") \
            .select("username") \
            .eq("id", agent_id) \
            .eq("role", "agent") \
            .eq("agent_status", "approved") \
            .limit(1) \
            .execute()
        if not agent_res.data:
            return {"status": "error", "message": "Agent not found or not approved"}

        products = get_checker_products()
        product = next((p for p in products if p.get("name", "").upper() == payload.checker_type), None)
        if not product:
            return {"status": "error", "message": "Checker type not available"}
        if not product.get("inStock"):
            return {"status": "error", "message": f"{payload.checker_type} checkers are out of stock"}

        # Agents pay their own cost (CHECKER_AGENT_BASE_PRICE), not the
        # customer-facing retail price on `product["price"]`.
        unit_cost   = CHECKER_AGENT_BASE_PRICE
        total_cost  = round(unit_cost * payload.quantity, 2)
        if total_cost <= 0:
            return {"status": "error", "message": "Invalid checker price"}

        # ── DUPLICATE GUARD — same spirit as agent_buy_data ─────────────
        dupe_floor = (utc_now() - timedelta(minutes=5)).isoformat()
        dupe_res = supabase.table("checkers") \
            .select("id, created_at") \
            .eq("agent_id", agent_id) \
            .eq("checker_type", payload.checker_type) \
            .eq("phone_number", payload.phone_number) \
            .gte("created_at", dupe_floor) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        if dupe_res.data:
            last_order_at = parse_db_dt(dupe_res.data[0]["created_at"])
            wait_seconds = max(int((timedelta(minutes=5) - (utc_now() - last_order_at)).total_seconds()), 1)
            return {
                "status": "error",
                "message": f"You just bought {payload.checker_type} for {payload.phone_number} moments ago. Please wait {wait_seconds}s.",
                "duplicate": True,
                "retry_after_seconds": wait_seconds,
            }

        wallet_res = supabase.table("agent_wallets").select("balance").eq("agent_id", agent_id).limit(1).execute()
        wallet_balance = float(wallet_res.data[0]["balance"]) if wallet_res.data else 0.0
        if wallet_balance < total_cost:
            return {"status": "error", "message": f"Insufficient wallet balance. Need GH₵ {total_cost:.2f}, have GH₵ {wallet_balance:.2f}"}

        new_balance = round(wallet_balance - total_cost, 2)
        supabase.table("agent_wallets").update({"balance": new_balance}).eq("agent_id", agent_id).execute()

        reference = f"CHK-AGT-{agent_id}-{uuid.uuid4().hex[:10].upper()}"

        checker_res = supabase.table("checkers").insert({
            "agent_id":     agent_id,
            "checker_type": payload.checker_type,
            "phone_number": payload.phone_number,
            "quantity":     payload.quantity,
            "price":        total_cost,
            "evosdata_ref": reference,
            "paystack_ref": reference,
            "status":       "processing",
        }).execute()

        if not checker_res.data:
            supabase.table("agent_wallets").update({"balance": wallet_balance}).eq("agent_id", agent_id).execute()
            return {"status": "error", "message": "Failed to create checker order"}

        checker_id = checker_res.data[0]["id"]

        supabase.table("agent_transactions").insert({
            "agent_id":  agent_id,
            "type":      "debit",
            "amount":    total_cost,
            "reference": reference,
            "order_id":  checker_id,
        }).execute()

        try:
            fresh = supabase.table("checkers").select("*").eq("id", checker_id).limit(1).execute().data[0]
            dispatch_checker_order(fresh)
        except Exception as dispatch_err:
            logger.error("AGENT BUY CHECKER DISPATCH ERROR: %s", str(dispatch_err))
            # Payment already taken from wallet — leave as "processing" so the
            # retry job's checker equivalent can pick it up rather than silently
            # failing and stranding a paid order. See note below on retry job scope.
            supabase.table("checkers").update({"status": "processing"}).eq("id", checker_id).execute()

        return {
            "status":             "success",
            "message":            f"{payload.quantity}x {payload.checker_type} queued for {payload.phone_number}",
            "reference":          reference,
            "checker_id":         checker_id,
            "new_wallet_balance": new_balance,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AGENT BUY CHECKER ERROR: %s", str(e))
        return {"status": "error", "message": "Something went wrong. Please try again."}
        
# =========================
# AFA REGISTRATION (MTN SIM) — fulfilled through Swift Data Link
# Customers pay via Paystack; approved agents pay their base price from wallet.
# Statuses: pending_payment → paid → processing → successful
#           failed   = our call to SDL didn't land (retryable, picked up by retry job)
#           rejected = SDL refused the details (needs a fix, not a retry; agents auto-refunded)
# =========================
AFA_SELL_PRICE  = float(os.getenv("AFA_SELL_PRICE", "20.00"))   # customer price
AFA_AGENT_PRICE = float(os.getenv("AFA_AGENT_PRICE", "17.00"))  # agent wallet cost
AFA_WEBHOOK_URL = os.getenv("AFA_WEBHOOK_URL", SWIFT_DATA_LINK_WEBHOOK)

GHANA_CARD_RE = re.compile(r"^GHA-\d{9}-\d$")
MTN_PREFIXES  = ("024", "025", "053", "054", "055", "059")
GHANA_REGIONS = [
    "Greater Accra", "Ashanti", "Western", "Western North", "Central", "Eastern",
    "Volta", "Oti", "Northern", "Savannah", "North East", "Upper East",
    "Upper West", "Bono", "Bono East", "Ahafo",
]


def _afa_clean_fields(v: dict) -> dict:
    name = re.sub(r"\s+", " ", (v.get("name") or "").strip())
    phone = re.sub(r"[\s\-\(\)]", "", v.get("phone_number") or "")
    if phone.startswith("+233"):
        phone = "0" + phone[4:]
    elif phone.startswith("233") and len(phone) == 12:
        phone = "0" + phone[3:]
    id_number = (v.get("id_number") or "").strip().upper()
    if len(name) < 3:
        raise ValueError("Enter the full name as it appears on the Ghana Card")
    if not re.match(r"^0\d{9}$", phone) or phone[:3] not in MTN_PREFIXES:
        raise ValueError("AFA registration is for MTN numbers only (e.g. 0551234567)")
    if not GHANA_CARD_RE.match(id_number):
        raise ValueError("Ghana Card must look like GHA-123456789-0")
    if v.get("region") not in GHANA_REGIONS:
        raise ValueError("Select a valid region")
    try:
        dob = datetime.strptime(v.get("date_of_birth") or "", "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Date of birth must be YYYY-MM-DD")
    today = utc_now().date()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age < 18 or age > 110:
        raise ValueError("Registrant must be 18 or older")
    return {"name": name, "phone_number": phone, "id_number": id_number, "date_of_birth": dob.isoformat()}


class AfaFields(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    phone_number: str = Field(min_length=9, max_length=16)
    id_number: str = Field(min_length=10, max_length=20)
    occupation: str = Field(min_length=2, max_length=60)
    location: str = Field(min_length=2, max_length=80)
    region: str
    date_of_birth: str

    def cleaned(self) -> dict:
        base = _afa_clean_fields(self.dict())
        return {
            **base,
            "occupation": self.occupation.strip(),
            "location":   self.location.strip(),
            "region":     self.region,
        }


class CreateAfaRequest(AfaFields):
    user_id: Optional[int] = None
    email: Optional[EmailStr] = None


class AgentBuyAfaRequest(AfaFields):
    agent_id: int


def map_afa_status(raw) -> str:
    s = str(raw or "").strip().lower()
    if s in ("approved", "completed", "complete", "successful", "success", "registered", "done", "delivered", "resolved"):
        return "successful"
    if s in ("rejected", "failed", "cancelled", "canceled", "declined", "refunded"):
        return "rejected"
    return "processing"


def _sdl_afa_headers(idem: str = None) -> dict:
    h = {"x-api-key": SWIFT_DATA_LINK_API_KEY, "Content-Type": "application/json"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


def refund_agent_afa(row: dict, reason: str):
    """Give an agent their wallet debit back, once."""
    agent_id = row.get("agent_id")
    if not agent_id:
        return
    claimed = supabase.table("afa_registrations").update({"status": "rejected", "failure_reason": reason[:300]}) \
        .eq("id", row["id"]).neq("status", "rejected").execute()
    if not claimed.data:
        return  # already refunded
    w = supabase.table("agent_wallets").select("balance").eq("agent_id", agent_id).limit(1).execute()
    if not w.data:
        logger.error("AFA REFUND: no wallet for agent %s (registration %s)", agent_id, row["id"])
        return
    new_bal = round(float(w.data[0]["balance"]) + float(row["price"]), 2)
    supabase.table("agent_wallets").update({"balance": new_bal}).eq("agent_id", agent_id).execute()
    supabase.table("agent_transactions").insert({
        "agent_id": agent_id, "type": "credit", "amount": float(row["price"]),
        "reference": f"{row['evosdata_ref']}-REFUND", "order_id": row["id"],
    }).execute()
    logger.info("AFA REFUND: GH₵%s returned to agent %s", row["price"], agent_id)


def dispatch_afa_registration(row: dict) -> str:
    """
    Submit a paid registration to Swift Data Link. Returns the new status.
    Raises only when the outcome is unknown/retryable (network, 5xx, 429) —
    the Idempotency-Key (our evosdata_ref) makes re-sending safe.
    """
    payload = {
        "name":        row["full_name"],
        "phoneNumber": row["phone_number"],
        "idNumber":    row["id_number"],
        "occupation":  row["occupation"],
        "location":    row["location"],
        "region":      row["region"],
        "dateOfBirth": str(row["date_of_birth"])[:10],
        "webhookUrl":  AFA_WEBHOOK_URL,
    }
    res = requests.post(
        f"{SWIFT_DATA_LINK_BASE}/afa/register",
        headers=_sdl_afa_headers(row["evosdata_ref"]),
        json=payload,
        timeout=BG_TIMEOUT,
    )
    try:
        data = res.json()
    except Exception:
        data = {}

    if res.status_code == 429 or res.status_code >= 500:
        raise RuntimeError(f"SDL AFA unavailable ({res.status_code})")

    if res.ok and data.get("success") is not False:
        reg = data.get("registration") or data.get("data") or {}
        reg_id = reg.get("registrationId") or reg.get("id") or data.get("registrationId") or data.get("id")
        update = {
            "status": map_afa_status(reg.get("status") or data.get("status") or "pending"),
            "provider_status": str(reg.get("status") or data.get("status") or "pending"),
            "updated_at": utc_now().isoformat(),
        }
        if reg_id:
            update["sdl_registration_id"] = str(reg_id)
        supabase.table("afa_registrations").update(update).eq("id", row["id"]).execute()
        return update["status"]

    reason = str(data.get("error") or data.get("message") or f"HTTP {res.status_code}")
    logger.warning("AFA DISPATCH REJECTED: reg %s — %s", row["id"], reason)
    if row.get("agent_id"):
        refund_agent_afa(row, reason)
    else:
        supabase.table("afa_registrations").update({
            "status": "rejected", "failure_reason": reason[:300], "updated_at": utc_now().isoformat(),
        }).eq("id", row["id"]).execute()
    return "rejected"


def sync_afa_from_sdl(row: dict) -> dict:
    """Poll SDL for a registration we've already submitted (webhook fallback)."""
    ident = row.get("sdl_registration_id") or row.get("phone_number")
    try:
        res = requests.get(f"{SWIFT_DATA_LINK_BASE}/afa/status/{ident}", headers=_sdl_afa_headers(), timeout=REQUEST_TIMEOUT)
        data = res.json()
    except Exception as e:
        logger.warning("AFA SYNC: %s", e)
        return row
    reg = data.get("registration") or {}
    if not reg:
        return row
    new_status = map_afa_status(reg.get("status"))
    if new_status != row["status"] and row["status"] != "rejected":
        if new_status == "rejected" and row.get("agent_id"):
            refund_agent_afa(row, str(reg.get("rejectionReason") or reg.get("reason") or "Rejected by provider"))
        else:
            supabase.table("afa_registrations").update({
                "status": new_status, "provider_status": str(reg.get("status")),
                "failure_reason": str(reg.get("rejectionReason") or reg.get("reason") or "")[:300] or None,
                "updated_at": utc_now().isoformat(),
            }).eq("id", row["id"]).execute()
        fresh = supabase.table("afa_registrations").select("*").eq("id", row["id"]).limit(1).execute()
        return fresh.data[0] if fresh.data else row
    return row


def _afa_public(row: dict) -> dict:
    idn = row.get("id_number") or ""
    return {
        "reference":     row.get("paystack_ref") or row.get("evosdata_ref"),
        "evosdata_ref":  row.get("evosdata_ref"),
        "status":        row.get("status"),
        "name":          row.get("full_name"),
        "phone_number":  row.get("phone_number"),
        "id_number":     (idn[:4] + "•••••" + idn[-3:]) if len(idn) > 8 else "",
        "region":        row.get("region"),
        "price":         row.get("price"),
        "failure_reason": row.get("failure_reason") if row.get("status") == "rejected" else None,
        "created_at":    row.get("created_at"),
    }


def _afa_insert(agent_or_user: dict, f: dict, price: float, ref: str, paystack_ref: str, status: str):
    return supabase.table("afa_registrations").insert({
        **agent_or_user,
        "full_name": f["name"], "phone_number": f["phone_number"], "id_number": f["id_number"],
        "occupation": f["occupation"], "location": f["location"], "region": f["region"],
        "date_of_birth": f["date_of_birth"], "price": price,
        "evosdata_ref": ref, "paystack_ref": paystack_ref, "status": status,
    }).execute()


@router.get("/afa/info")
@limiter.limit("60/minute")
def afa_info(request: Request):
    return {"price": AFA_SELL_PRICE, "regions": GHANA_REGIONS, "network": "MTN"}


@router.post("/afa/create")
@limiter.limit("10/minute")
def create_afa_registration(request: Request, data: CreateAfaRequest):
    try:
        data.user_id = resolve_order_identity(request, data.user_id)
        try:
            f = data.cleaned()
        except ValueError as ve:
            raise HTTPException(400, str(ve))

        # Same person + number paying twice in 10 min is almost always a double-tap
        dupe_floor = (utc_now() - timedelta(minutes=10)).isoformat()
        dupe = supabase.table("afa_registrations").select("id") \
            .eq("phone_number", f["phone_number"]).in_("status", ["paid", "processing", "successful"]) \
            .gte("created_at", dupe_floor).limit(1).execute()
        if dupe.data:
            raise HTTPException(400, "A registration for this number was just submitted. Check its status first.")

        if data.user_id:
            u = supabase.table("users").select("email").eq("id", data.user_id).limit(1).execute()
            if not u.data:
                raise HTTPException(404, "User not found")
            email = u.data[0]["email"]
        else:
            email = data.email or "guest@evoshub.com"

        try:
            ps = requests.post(
                "https://api.paystack.co/transaction/initialize",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
                json={"email": email, "amount": int(round(AFA_SELL_PRICE * 100)),
                      "callback_url": f"{callback_base(request)}/success?type=afa"},
                timeout=REQUEST_TIMEOUT,
            ).json()
        except requests.exceptions.RequestException:
            raise HTTPException(500, "Payment service error")
        if not ps.get("status"):
            raise HTTPException(400, "Payment init failed")

        ref = ps["data"]["reference"]
        _afa_insert(
            {"user_id": data.user_id, "guest_email": None if data.user_id else email},
            f, AFA_SELL_PRICE, f"AFA-{uuid.uuid4().hex[:8].upper()}", ref, "pending_payment",
        )
        return {"status": True, "payment_url": ps["data"]["authorization_url"], "reference": ref}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("CREATE AFA ERROR: %s", str(e))
        raise HTTPException(500, "Server error")


def mark_afa_paid_and_dispatch(row: dict):
    """Called from Paystack webhook / status check once payment is confirmed."""
    supabase.table("afa_registrations").update({"status": "paid", "updated_at": utc_now().isoformat()}).eq("id", row["id"]).execute()
    fresh = supabase.table("afa_registrations").select("*").eq("id", row["id"]).limit(1).execute().data[0]
    try:
        dispatch_afa_registration(fresh)
    except Exception as e:
        logger.error("AFA DISPATCH ERROR (will retry): reg %s: %s", row["id"], e)
        supabase.table("afa_registrations").update({"status": "failed", "updated_at": utc_now().isoformat()}).eq("id", row["id"]).execute()


@router.get("/afa/status/{reference}")
@limiter.limit("20/minute")
async def get_afa_status(request: Request, reference: str):
    try:
        if not re.match(r"^[A-Za-z0-9_\-]{4,80}$", reference):
            raise HTTPException(404, "Registration not found")
        res = supabase.table("afa_registrations").select("*") \
            .or_(f"paystack_ref.eq.{reference},evosdata_ref.eq.{reference}").limit(1).execute()
        if not res.data:
            raise HTTPException(404, "Registration not found")
        row = res.data[0]

        # Customer bounced back from Paystack before the webhook landed
        if row["status"] == "pending_payment" and row.get("paystack_ref"):
            try:
                async with httpx.AsyncClient() as client:
                    pres = await client.get(
                        f"https://api.paystack.co/transaction/verify/{row['paystack_ref']}",
                        headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"}, timeout=15)
                if pres.json().get("data", {}).get("status") == "success":
                    cur = supabase.table("afa_registrations").select("*").eq("id", row["id"]).limit(1).execute().data[0]
                    if cur["status"] == "pending_payment":
                        await asyncio.to_thread(mark_afa_paid_and_dispatch, cur)
            except Exception as ve:
                logger.error("AFA STATUS verify error %s: %s", reference, ve)
            row = supabase.table("afa_registrations").select("*").eq("id", row["id"]).limit(1).execute().data[0]

        elif row["status"] == "processing" and row.get("sdl_registration_id"):
            row = await asyncio.to_thread(sync_afa_from_sdl, row)

        return _afa_public(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AFA STATUS ERROR: %s", str(e))
        raise HTTPException(500, "Failed to fetch registration status")


@router.get("/afa/track")
@limiter.limit("20/minute")
def track_afa(request: Request, phone: str = Query(...)):
    try:
        cleaned = normalise_phone(phone)
        res = supabase.table("afa_registrations").select("*").eq("phone_number", cleaned) \
            .neq("status", "pending_payment").order("created_at", desc=True).limit(10).execute()
        return {"registrations": [_afa_public(r) for r in (res.data or [])]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AFA TRACK ERROR: %s", str(e))
        raise HTTPException(500, "Failed to fetch registrations")


@router.get("/agent/afa-info/{agent_id}")
def agent_afa_info(request: Request, agent_id: int, _: int = Depends(require_agent)):
    return {"price": AFA_AGENT_PRICE, "regions": GHANA_REGIONS}


@router.get("/agent/afa/{agent_id}")
def agent_afa_history(request: Request, agent_id: int, _: int = Depends(require_agent)):
    res = supabase.table("afa_registrations").select("*").eq("agent_id", agent_id) \
        .order("created_at", desc=True).limit(30).execute()
    return {"registrations": [_afa_public(r) for r in (res.data or [])]}


@router.post("/agent/buy-afa")
@limiter.limit("10/minute")
async def agent_buy_afa(request: Request, payload: AgentBuyAfaRequest):
    try:
        token = request.headers.get("X-Agent-Token", "")
        if not token or not verify_agent_token(token, payload.agent_id):
            raise HTTPException(status_code=403, detail="Forbidden")
        agent_id = payload.agent_id

        try:
            f = payload.cleaned()
        except ValueError as ve:
            return {"status": "error", "message": str(ve)}

        a = supabase.table("users").select("id").eq("id", agent_id).eq("role", "agent") \
            .eq("agent_status", "approved").limit(1).execute()
        if not a.data:
            return {"status": "error", "message": "Agent not found or not approved"}

        dupe_floor = (utc_now() - timedelta(minutes=10)).isoformat()
        dupe = supabase.table("afa_registrations").select("id") \
            .eq("phone_number", f["phone_number"]).in_("status", ["paid", "processing", "successful"]) \
            .gte("created_at", dupe_floor).limit(1).execute()
        if dupe.data:
            return {"status": "error", "message": "A registration for this number was just submitted. Please wait before retrying.", "duplicate": True}

        w = supabase.table("agent_wallets").select("balance").eq("agent_id", agent_id).limit(1).execute()
        balance = float(w.data[0]["balance"]) if w.data else 0.0
        if balance < AFA_AGENT_PRICE:
            return {"status": "error", "message": f"Insufficient wallet balance. Need GH₵ {AFA_AGENT_PRICE:.2f}, have GH₵ {balance:.2f}"}

        new_balance = round(balance - AFA_AGENT_PRICE, 2)
        supabase.table("agent_wallets").update({"balance": new_balance}).eq("agent_id", agent_id).execute()

        ref = f"AFA-AGT-{agent_id}-{uuid.uuid4().hex[:10].upper()}"
        ins = _afa_insert({"agent_id": agent_id}, f, AFA_AGENT_PRICE, ref, ref, "paid")
        if not ins.data:
            supabase.table("agent_wallets").update({"balance": balance}).eq("agent_id", agent_id).execute()
            return {"status": "error", "message": "Failed to create registration"}
        row = ins.data[0]

        supabase.table("agent_transactions").insert({
            "agent_id": agent_id, "type": "debit", "amount": AFA_AGENT_PRICE, "reference": ref, "order_id": row["id"],
        }).execute()

        try:
            outcome = await asyncio.to_thread(dispatch_afa_registration, row)
        except Exception as e:
            # Wallet already debited; leave as "failed" so the retry job resubmits (idempotent)
            logger.error("AGENT BUY AFA DISPATCH ERROR (will retry): %s", e)
            supabase.table("afa_registrations").update({"status": "failed"}).eq("id", row["id"]).execute()
            outcome = "queued"

        if outcome == "rejected":
            cur = supabase.table("afa_registrations").select("failure_reason").eq("id", row["id"]).limit(1).execute()
            reason = (cur.data[0].get("failure_reason") if cur.data else None) or "Registration was rejected"
            fresh_w = supabase.table("agent_wallets").select("balance").eq("agent_id", agent_id).limit(1).execute()
            return {"status": "error", "message": f"Registration rejected: {reason}. Your wallet was refunded.",
                    "new_wallet_balance": float(fresh_w.data[0]["balance"]) if fresh_w.data else new_balance}

        return {"status": "success", "message": f"AFA registration submitted for {f['phone_number']}",
                "reference": ref, "new_wallet_balance": new_balance}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AGENT BUY AFA ERROR: %s", str(e))
        return {"status": "error", "message": "Something went wrong. Please try again."}


# Resubmits paid registrations whose call to SDL failed (SDL's AFA endpoints
# share a 5/min rate limit, so 429s are expected under load). Safe to repeat:
# Idempotency-Key = evosdata_ref.
_afa_retry_running = False

async def retry_stuck_afa():
    global _afa_retry_running
    if _afa_retry_running:
        return
    _afa_retry_running = True
    await asyncio.sleep(200)
    while True:
        try:
            now = utc_now()
            rows = supabase.table("afa_registrations").select("*").eq("status", "failed") \
                .is_("sdl_registration_id", None) \
                .lte("updated_at", (now - timedelta(minutes=2)).isoformat()) \
                .gte("created_at", (now - timedelta(hours=24)).isoformat()).limit(5).execute().data or []
            for row in rows:
                try:
                    await asyncio.to_thread(dispatch_afa_registration, row)
                except Exception as e:
                    logger.warning("AFA RETRY: reg %s still failing: %s", row["id"], e)
                    supabase.table("afa_registrations").update({"updated_at": utc_now().isoformat()}).eq("id", row["id"]).execute()
                await asyncio.sleep(13)  # stay under SDL's 5/min limit
            # Anything stuck unpaid-looking agent rows or older than 24h failing → refund agents
            old = supabase.table("afa_registrations").select("*").eq("status", "failed") \
                .not_.is_("agent_id", None).lte("created_at", (now - timedelta(hours=24)).isoformat()).execute().data or []
            for row in old:
                refund_agent_afa(row, "Could not be submitted within 24h — auto-refunded")
        except Exception as e:
            logger.error("AFA RETRY LOOP ERROR: %s", e)
        await asyncio.sleep(120)


# =========================
# VERIFY NUMBER (DataMart pre-check)
# Informational only — never blocks a purchase. Any failure, timeout, or
# rate-limit from DataMart just falls back to recommendation "unknown" so
# the frontend can quietly skip the warning banner and let checkout proceed.
# =========================
def _can_call_datamart_verify() -> bool:
    now = time.time()
    with _verify_call_lock:
        global _verify_call_times
        _verify_call_times = [t for t in _verify_call_times if now - t < DATAMART_VERIFY_WINDOW]
        if len(_verify_call_times) >= DATAMART_VERIFY_LIMIT:
            return False
        _verify_call_times.append(now)
        return True


def _unknown_result(message: str) -> dict:
    return {
        "status": "success",
        "checked": False,
        "servable": True,
        "recommendation": "unknown",
        "message": message,
    }


@router.post("/verify-number")
@limiter.limit("20/minute")
def verify_number(request: Request, data: VerifyNumberRequest):
    phone = data.phoneNumber
    network = (data.network or "").upper()

    # DataMart's check only exists for MTN — anything else is a no-op pass-through
    if network and network != "MTN":
        return _unknown_result("Verification only applies to MTN numbers.")

    now = time.time()
    with _verify_cache_lock:
        cached = _verify_cache.get(phone)
        if cached and now - cached[0] < VERIFY_CACHE_TTL:
            result = dict(cached[1])
            result["cached"] = True
            return result

    if not _can_call_datamart_verify():
        return _unknown_result("Live check is busy right now — you can still continue.")

    try:
        resp = requests.post(
            f"{DATAMART_BASE}/verify-number",
            headers={"X-API-Key": DATAMART_API_KEY},
            json={"phoneNumber": phone},
            # (connect, read) — a single number here applies to *each* phase
            # separately, so timeout=5 could actually take up to ~10s total.
            # Bounding both explicitly keeps the worst case under ~9s, safely
            # inside the frontend's wait window (see verifyNumber in api.js).
            timeout=(3, 6),
        )
    except requests.exceptions.RequestException as e:
        logger.warning("VERIFY NUMBER: request error: %s", str(e))
        return _unknown_result("Couldn't reach the verification service — you can still continue.")

    if resp.status_code == 429:
        return _unknown_result("Live check is busy right now — you can still continue.")

    if resp.status_code == 503:
        return _unknown_result("Verification network is momentarily unavailable — you can still continue.")

    if resp.status_code != 200:
        logger.warning("VERIFY NUMBER: DataMart returned %s: %s", resp.status_code, resp.text[:200])
        return _unknown_result("Couldn't verify right now — you can still continue.")

    try:
        dm_data = resp.json().get("data", {})
    except ValueError:
        return _unknown_result("Couldn't verify right now — you can still continue.")

    result = {
        "status": "success",
        "checked": True,
        "phoneNumber": dm_data.get("phoneNumber", phone),
        "network": dm_data.get("network", "MTN"),
        "servable": dm_data.get("servable", True),
        "recommendation": dm_data.get("recommendation", "unknown"),
        "message": dm_data.get("message", ""),
        "cached": False,
    }

    with _verify_cache_lock:
        # opportunistically drop stale entries so this dict doesn't grow forever
        for k in [k for k, v in _verify_cache.items() if now - v[0] > VERIFY_CACHE_TTL]:
            del _verify_cache[k]
        _verify_cache[phone] = (now, result)

    return result


# =========================
# BACKGROUND: RETRY STUCK ORDERS
# FIX: retry loop now walks the FULL provider chain for each order's network
#      instead of using a single fixed provider. Each order tracks how many
#      times it's been tried on its current provider (retry_attempts) and
#      which tier of the chain it's on (provider_priority). After
#      MAX_ATTEMPTS_PER_PROVIDER failures, handle_provider_failure() escalates
#      to the next-priority provider. Order only gets marked "failed" once
#      every provider in the chain is exhausted AND it's >= 3h old.
# =========================

_retry_running = False

async def retry_stuck_orders():
    global _retry_running
    if _retry_running:
        logger.info("RETRY JOB: already running, skipping duplicate")
        return

    _retry_running = True
    await asyncio.sleep(60)

    while True:
        try:
            logger.info("RETRY JOB: scanning for stuck orders...")
            now   = utc_now()
            floor = (now - timedelta(minutes=10)).isoformat()

            stuck = supabase.table("orders") \
                .select("*") \
                .eq("status", "processing") \
                .not_.is_("paystack_ref", None) \
                .is_("datamart_ref", None) \
                .lte("created_at", floor) \
                .execute()

            orders = stuck.data or []
            logger.info("RETRY JOB: %d stuck orders found", len(orders))

            for order in orders:
                try:
                    chain = get_provider_chain(order["network"])
                    if not chain:
                        logger.info("RETRY JOB: no provider chain for order %s", order['id'])
                        continue

                    current_idx = min(int(order.get("provider_priority") or 1) - 1, len(chain) - 1)
                    provider = chain[current_idx]

                    logger.info(
                        "RETRY JOB: retrying order %s via %s (tier %d/%d, attempt %d/%d)",
                        order['id'], provider, current_idx + 1, len(chain),
                        int(order.get("retry_attempts") or 0) + 1, MAX_ATTEMPTS_PER_PROVIDER
                    )

                    # ── DATAMART ──────────────────────────────────────────
                    if provider == "DATAMART":
                        dm_response = datamart_stock.purchase_post(
                            f"{DATAMART_BASE}/purchase",
                            headers={"X-API-Key": DATAMART_API_KEY},
                            json={
                                "phoneNumber": order["phone_number"],
                                "network":     NETWORK_MAP.get(order["network"]),
                                "capacity":    extract_capacity(order["bundle"]),
                                "gateway":     "wallet"
                            },
                            timeout=REQUEST_TIMEOUT
                        )
                        dm      = dm_response.json()
                        dm_data = dm.get("data", {})

                        if dm_data.get("orderReference"):
                            supabase.table("orders").update({
                                "status":            "processing",
                                "datamart_ref":      dm_data.get("orderReference"),
                                "datamart_order_id": dm_data.get("orderId")
                            }).eq("id", order["id"]).execute()

                            if order.get("paystack_ref") and not str(order["paystack_ref"]).startswith("EVOS-AGT-"):
                                process_agent_profit(order["id"], order["paystack_ref"])

                            logger.info("RETRY JOB: order %s sent to DATAMART ✅", order['id'])
                        else:
                            logger.warning("RETRY JOB: DATAMART rejected order %s: %s", order['id'], dm)
                            handle_provider_failure(order, chain, current_idx, provider, dm)

                    # ── BUNDLES GHANA ──────────────────────────────────────
                    elif provider == "BUNDLES_GHANA":
                        BG_NETWORK_MAP = {
                            "MTN":        "MTN",
                            "TELECEL":    "Telecel",
                            "AIRTELTIGO": "AirtelTigo",
                            "AT":         "AirtelTigo",
                        }
                        network_name = BG_NETWORK_MAP.get(order["network"].upper(), order["network"])
                        bg_bundles   = call_bundles_ghana(f"/bundles?network={network_name}")

                        if not bg_bundles.get("success"):
                            logger.warning("RETRY JOB: BG bundle fetch failed for order %s", order['id'])
                            handle_provider_failure(order, chain, current_idx, provider, bg_bundles)
                            continue

                        bundle_volume = order["bundle"].upper().replace(" ", "")
                        matched = next(
                            (b for b in bg_bundles.get("bundles", [])
                             if b.get("volume", "").upper().replace(" ", "") == bundle_volume
                             and b.get("status") == "active"),
                            None
                        )

                        if not matched:
                            logger.warning("RETRY JOB: no BG bundle match for order %s", order['id'])
                            handle_provider_failure(order, chain, current_idx, provider, "no bundle match")
                            continue

                        try:
                            bg_order = call_bundles_ghana(
                                "/order",
                                method="POST",
                                body={
                                    "bundle_id":   matched["id"],
                                    "phone":       order["phone_number"],
                                    "webhook_url": "https://api.evosdata.xyz/webhook/bundlesghana"
                                }
                            )
                        except Exception as bg_err:
                            logger.error("RETRY JOB: BG call error for order %s: %s", order['id'], str(bg_err))
                            handle_provider_failure(order, chain, current_idx, provider, str(bg_err))
                            continue

                        if bg_order.get("success"):
                            supabase.table("orders").update({
                                "status":            "processing",
                                "datamart_ref":      bg_order["order"]["reference"],
                                "datamart_order_id": str(bg_order["order"]["id"])
                            }).eq("id", order["id"]).execute()

                            if order.get("paystack_ref") and not str(order["paystack_ref"]).startswith("EVOS-AGT-"):
                                process_agent_profit(order["id"], order["paystack_ref"])

                            logger.info("RETRY JOB: order %s sent to BUNDLES_GHANA ✅", order['id'])
                        else:
                            msg        = bg_order.get("message", "")
                            order_type = bg_order.get("type", "")

                            # 409 conflict — BG already has this order, recover the ref
                            if order_type == "ORDER_FAILED" and "Ref:" in msg:
                                ref_match = re.search(r'Ref:\s*([\w\-]+)', msg)
                                if ref_match:
                                    existing_ref = ref_match.group(1)
                                    supabase.table("orders").update({
                                        "status":       "processing",
                                        "datamart_ref": existing_ref,
                                    }).eq("id", order["id"]).execute()
                                    logger.info("RETRY JOB: order %s recovered from 409 — ref=%s ✅", order['id'], existing_ref)
                                    continue

                            logger.warning("RETRY JOB: BG rejected order %s: %s", order['id'], bg_order)
                            handle_provider_failure(order, chain, current_idx, provider, bg_order)

                    # ── SWIFT DATA LINK ────────────────────────────────────
                    elif provider == "SWIFT_DATA_LINK":
                        volume = float(extract_capacity(order["bundle"]) or 0)
                        sdl    = call_swift_data_link(
                            network=order["network"],
                            volume=volume,
                            phone=order["phone_number"],
                        )

                        if sdl.get("success"):
                            supabase.table("orders").update({
                                "status":            "processing",
                                "datamart_ref":      sdl.get("reference"),
                                "datamart_order_id": sdl.get("orderId"),
                            }).eq("id", order["id"]).execute()

                            if order.get("paystack_ref") and not str(order["paystack_ref"]).startswith("EVOS-AGT-"):
                                process_agent_profit(order["id"], order["paystack_ref"])

                            logger.info("RETRY JOB: order %s sent to SWIFT_DATA_LINK ✅", order['id'])
                        else:
                            logger.warning("RETRY JOB: SDL rejected order %s: %s", order['id'], sdl)
                            handle_provider_failure(order, chain, current_idx, provider, sdl)

                    # ── AGYEKUMDATA ────────────────────────────────────────
                    elif provider == "AGYEKUMDATA":
                        package_id = get_agyekumdata_package_id(order["network"], order["bundle"])
                        raw_ref    = (
                            order.get("paystack_ref")
                            or order.get("evosdata_ref")
                            or str(order["id"])
                        )
                        safe_ref   = sanitise_agyekumdata_ref(raw_ref)
                        agd        = call_agyekumdata_purchase(
                            package_id=package_id,
                            phone=order["phone_number"],
                            client_reference=raw_ref,
                        )

                        if agd.get("success"):
                            agd_data = agd.get("data", {})
                            supabase.table("orders").update({
                                "status":            "processing",
                                "datamart_ref":      agd_data.get("clientReference") or safe_ref,
                                "datamart_order_id": agd_data.get("orderId"),
                            }).eq("id", order["id"]).execute()

                            if order.get("paystack_ref") and not str(order["paystack_ref"]).startswith("EVOS-AGT-"):
                                process_agent_profit(order["id"], order["paystack_ref"])

                            logger.info("RETRY JOB: order %s sent to AGYEKUMDATA ✅", order['id'])
                        else:
                            err_msg = str(agd.get("error", ""))
                            logger.warning("RETRY JOB: AGYEKUMDATA rejected order %s: %s", order['id'], agd)

                            # Duplicate clientReference — order was already submitted, recover it
                            if "Duplicate clientReference" in err_msg:
                                supabase.table("orders").update({
                                    "status":       "processing",
                                    "datamart_ref": safe_ref,
                                }).eq("id", order["id"]).execute()
                                logger.info(
                                    "RETRY JOB: order %s recovered from duplicate clientReference ✅",
                                    order['id']
                                )
                                continue

                            handle_provider_failure(order, chain, current_idx, provider, agd)

                except Exception as e:
                    logger.error("RETRY JOB: error on order %s: %s", order.get('id'), str(e))

            # ── STATUS SYNC ───────────────────────────────────────────────
            logger.info("STATUS SYNC: scanning for unresolved processing orders...")
            sync_cutoff = (now - timedelta(days=3)).isoformat()

            processing = supabase.table("orders") \
                .select("*") \
                .eq("status", "processing") \
                .not_.is_("datamart_ref", None) \
                .gte("created_at", sync_cutoff) \
                .execute()

            proc_orders = processing.data or []
            logger.info("STATUS SYNC: %d orders to check", len(proc_orders))

            for order in proc_orders:
                try:
                    provider = get_provider(order["network"])
                    ref      = order.get("datamart_ref")
                    order_id = order.get("datamart_order_id")

                    if provider == "DATAMART":
                        tracker = order_id or ref
                        if not tracker:
                            continue
                        dm = requests.get(
                            f"{DATAMART_BASE}/order-status/{tracker}",
                            headers={"X-API-Key": DATAMART_API_KEY},
                            timeout=REQUEST_TIMEOUT
                        )
                        payload = dm.json()
                        status  = str(payload.get("data", {}).get("orderStatus", "")).lower()

                    elif provider == "BUNDLES_GHANA":
                        if not ref:
                            continue
                        bg     = call_bundles_ghana(f"/order/status/{ref}")
                        status = str(bg.get("order", {}).get("status", "processing")).lower()

                    elif provider == "SWIFT_DATA_LINK":
                        tracker = ref or order_id
                        if not tracker:
                            continue
                        sdl_res = requests.get(
                            f"{SWIFT_DATA_LINK_BASE}/order/status/{tracker}",
                            headers={"x-api-key": SWIFT_DATA_LINK_API_KEY},
                            timeout=REQUEST_TIMEOUT
                        ).json()
                        status = str(sdl_res.get("order", {}).get("status", "")).lower()

                    elif provider == "AGYEKUMDATA":
                        client_ref = ref
                        if not client_ref:
                            continue
                        agd_res = call_agyekumdata_status(client_reference=client_ref)
                        status = str(agd_res.get("data", {}).get("status", "processing")).lower()
                        logger.info(
                            "STATUS SYNC: AGYEKUMDATA order %s clientRef=%s status=%s",
                            order['id'], client_ref, status
                        )

                    else:
                        continue

                    final_status = (
                        "successful"
                        if status in ["completed", "success", "delivered", "successful", "resolved"]
                        else "failed"
                        if status in ["failed", "cancelled", "refunded"]
                        else None
                    )

                    if final_status:
                        supabase.table("orders") \
                            .update({"status": final_status}) \
                            .eq("id", order["id"]) \
                            .execute()
                        logger.info("STATUS SYNC: order %s → %s ✅", order['id'], final_status)
                    else:
                        logger.info(
                            "STATUS SYNC: order %s still showing '%s' on provider — will poll again next cycle",
                            order['id'], status
                        )

                except Exception as e:
                    logger.error("STATUS SYNC: error on order %s: %s", order.get('id'), str(e))

        except Exception as e:
            logger.error("RETRY JOB ERROR: %s", str(e))

        await asyncio.sleep(300)


# =========================
# BACKGROUND: RETRY STUCK DEPOSITS
# =========================

_deposit_retry_running = False

async def retry_stuck_deposits():
    global _deposit_retry_running
    if _deposit_retry_running:
        logger.info("DEPOSIT RETRY: already running, skipping duplicate")
        return

    _deposit_retry_running = True
    await asyncio.sleep(90)

    while True:
        try:
            logger.info("DEPOSIT RETRY: scanning for stuck deposits...")

            now    = utc_now()
            floor  = (now - timedelta(minutes=5)).isoformat()
            cutoff = (now - timedelta(hours=2)).isoformat()

            stuck = supabase.table("wallet_deposits") \
                .select("*") \
                .eq("status", "pending") \
                .lte("created_at", floor) \
                .gte("created_at", cutoff) \
                .execute()

            deposits = stuck.data or []
            logger.info("DEPOSIT RETRY: %d stuck deposits found", len(deposits))

            for deposit in deposits:
                dep_id        = deposit.get("id")
                agent_id      = deposit.get("agent_id")
                credit_amount = float(deposit.get("amount", 0))
                verify_ref    = deposit.get("paystack_ref") or deposit.get("reference")

                if not verify_ref or not agent_id:
                    logger.info("DEPOSIT RETRY: skipping deposit %s — missing ref or agent_id", dep_id)
                    continue

                if credit_amount <= 0:
                    logger.info("DEPOSIT RETRY: skipping deposit %s — invalid amount %s", dep_id, credit_amount)
                    continue

                try:
                    async with httpx.AsyncClient() as client:
                        res = await client.get(
                            f"https://api.paystack.co/transaction/verify/{verify_ref}",
                            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"},
                            timeout=15,
                        )
                        data = res.json()

                    paystack_status = data.get("data", {}).get("status", "")
                    logger.info("DEPOSIT RETRY: deposit %s — Paystack status: %s", dep_id, paystack_status)

                    if paystack_status != "success":
                        age = utc_now() - parse_db_dt(deposit["created_at"])
                        if age > timedelta(minutes=30):
                            supabase.table("wallet_deposits") \
                                .update({"status": "failed"}) \
                                .eq("id", dep_id) \
                                .execute()
                            logger.info("DEPOSIT RETRY: deposit %s marked failed — Paystack unpaid after 30min", dep_id)
                        else:
                            logger.info("DEPOSIT RETRY: deposit %s still pending on Paystack — will retry", dep_id)
                        continue

                    # ── ATOMIC CLAIM ──────────────────────────────────
                    # A plain "read status, then later write" check here left
                    # a gap that /agent/deposit/verify (fired from the
                    # frontend right after the Paystack redirect) could slip
                    # through at the same time, double-crediting the same
                    # deposit. Flipping status here — gated on it not already
                    # being "credited" — means only ONE caller's update can
                    # actually affect a row; that's the one that proceeds.
                    claim = supabase.table("wallet_deposits") \
                        .update({"status": "credited"}) \
                        .eq("id", dep_id) \
                        .neq("status", "credited") \
                        .execute()

                    if not claim.data:
                        logger.info("DEPOSIT RETRY: deposit %s already claimed elsewhere, skipping", dep_id)
                        continue

                    # Belt-and-suspenders: also guard on the transaction
                    # reference itself, same pattern used for order/checker
                    # profit crediting elsewhere in this file.
                    existing_tx = supabase.table("agent_transactions") \
                        .select("id") \
                        .eq("reference", deposit.get("reference")) \
                        .limit(1) \
                        .execute()
                    if existing_tx.data:
                        logger.info("DEPOSIT RETRY: deposit %s already has a credit transaction, skipping", dep_id)
                        continue

                    wallet_res = supabase.table("agent_wallets") \
                        .select("balance") \
                        .eq("agent_id", agent_id) \
                        .limit(1) \
                        .execute()

                    if wallet_res.data:
                        current     = float(wallet_res.data[0]["balance"] or 0)
                        new_balance = round(current + credit_amount, 2)
                        supabase.table("agent_wallets") \
                            .update({"balance": new_balance}) \
                            .eq("agent_id", agent_id) \
                            .execute()
                    else:
                        new_balance = round(credit_amount, 2)
                        supabase.table("agent_wallets") \
                            .insert({"agent_id": agent_id, "balance": new_balance}) \
                            .execute()

                    supabase.table("agent_transactions").insert({
                        "agent_id":  agent_id,
                        "type":      "credit",
                        "amount":    credit_amount,
                        "reference": deposit.get("reference"),
                    }).execute()

                    logger.info(
                        "DEPOSIT RETRY: deposit %s credited GH₵%s to agent %s ✅ — new balance: GH₵%s",
                        dep_id, credit_amount, agent_id, new_balance
                    )

                except Exception as e:
                    logger.error("DEPOSIT RETRY: error on deposit %s: %s", dep_id, str(e))

        except Exception as e:
            logger.error("DEPOSIT RETRY ERROR: %s", str(e))

        await asyncio.sleep(300)


# =========================
# BACKGROUND: RETRY STUCK ORDER PAYMENTS
# Orders can get stuck in "pending_payment" if the Paystack webhook never
# fires (network blip, webhook retries exhausted, etc.), and can land in
# "failed" if Paystack DID charge the customer but the provider dispatch
# never actually happened (order failed before reaching a provider). This
# job never trusts our own stored status — it always re-verifies with
# Paystack itself before touching anything, exactly like
# retry_stuck_deposits() does for wallet deposits.
#
# Scope: only orders with NO datamart_ref. If datamart_ref is already set,
# the order already reached a provider and belongs to retry_stuck_orders()'
# provider-escalation chain instead — re-dispatching here would risk a
# double-submit to the provider.
# =========================

_order_payment_retry_running = False

async def retry_stuck_order_payments():
    global _order_payment_retry_running
    if _order_payment_retry_running:
        logger.info("ORDER PAYMENT RETRY: already running, skipping duplicate")
        return

    _order_payment_retry_running = True
    await asyncio.sleep(120)  # stagger start vs the other two background jobs

    while True:
        try:
            logger.info("ORDER PAYMENT RETRY: scanning for stuck order payments...")

            now    = utc_now()
            floor  = (now - timedelta(minutes=5)).isoformat()   # give the webhook a head start
            cutoff = (now - timedelta(hours=6)).isoformat()     # don't dig up ancient rows forever

            stuck = supabase.table("orders") \
                .select("*") \
                .in_("status", ["pending_payment", "failed"]) \
                .not_.is_("paystack_ref", None) \
                .is_("datamart_ref", None) \
                .lte("created_at", floor) \
                .gte("created_at", cutoff) \
                .execute()

            orders = stuck.data or []
            logger.info("ORDER PAYMENT RETRY: %d orders to check", len(orders))

            for order in orders:
                order_id  = order.get("id")
                reference = order.get("paystack_ref")

                if not reference:
                    continue

                # Agent buy-data orders are wallet-debited instantly and never
                # go through Paystack at all — nothing to verify here.
                if str(reference).startswith("EVOS-AGT-"):
                    continue

                try:
                    async with httpx.AsyncClient() as client:
                        res = await client.get(
                            f"https://api.paystack.co/transaction/verify/{reference}",
                            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"},
                            timeout=15,
                        )
                        data = res.json()

                    paystack_status = data.get("data", {}).get("status", "")
                    logger.info(
                        "ORDER PAYMENT RETRY: order %s ref=%s — Paystack status: %s",
                        order_id, reference, paystack_status
                    )

                    if paystack_status != "success":
                        if order["status"] == "pending_payment":
                            age = utc_now() - parse_db_dt(order["created_at"])
                            if age > timedelta(minutes=30):
                                supabase.table("orders").update({"status": "failed"}).eq("id", order_id).execute()
                                logger.info(
                                    "ORDER PAYMENT RETRY: order %s marked failed — Paystack unpaid after 30min",
                                    order_id
                                )
                            else:
                                logger.info(
                                    "ORDER PAYMENT RETRY: order %s still pending on Paystack — will retry",
                                    order_id
                                )
                        # already "failed" and Paystack still says not-success —
                        # nothing to do, leave it as is.
                        continue

                    # Paystack confirms the charge succeeded. Re-fetch the row
                    # fresh in case the webhook (or a previous cycle) already
                    # handled it in the meantime.
                    recheck = supabase.table("orders").select("*").eq("id", order_id).limit(1).execute()
                    if not recheck.data:
                        continue
                    fresh_order = recheck.data[0]
                    if fresh_order["status"] not in ("pending_payment", "failed") or fresh_order.get("datamart_ref"):
                        logger.info(
                            "ORDER PAYMENT RETRY: order %s already advanced (status=%s, datamart_ref=%s), skipping",
                            order_id, fresh_order["status"], fresh_order.get("datamart_ref")
                        )
                        continue

                    supabase.table("orders").update({"status": "paid"}).eq("id", order_id).execute()
                    logger.info("ORDER PAYMENT RETRY: order %s confirmed paid by Paystack ✅", order_id)

                    if fresh_order.get("user_id"):
                        increment_user_orders(fresh_order["user_id"])

                    provider = get_provider(fresh_order["network"])
                    logger.info("ORDER PAYMENT RETRY: resolved provider=%s for order %s", provider, order_id)

                    try:
                        if provider == "DATAMART":
                            dm_response = datamart_stock.purchase_post(
                                f"{DATAMART_BASE}/purchase",
                                headers={"X-API-Key": DATAMART_API_KEY},
                                json={
                                    "phoneNumber": fresh_order["phone_number"],
                                    "network":     NETWORK_MAP.get(fresh_order["network"]),
                                    "capacity":    extract_capacity(fresh_order["bundle"]),
                                    "gateway":     "wallet"
                                },
                                timeout=REQUEST_TIMEOUT
                            )
                            dm      = dm_response.json()
                            dm_data = dm.get("data", {})
                            supabase.table("orders").update({
                                "status":            "processing",
                                "datamart_ref":      dm_data.get("orderReference"),
                                "datamart_order_id": dm_data.get("orderId")
                            }).eq("id", order_id).execute()
                            process_agent_profit(order_id, reference)
                            logger.info("ORDER PAYMENT RETRY: order %s dispatched to DATAMART ✅", order_id)

                        elif provider == "BUNDLES_GHANA":
                            BG_NETWORK_MAP = {"MTN": "MTN", "TELECEL": "Telecel", "AIRTELTIGO": "AirtelTigo", "AT": "AirtelTigo"}
                            network_name = BG_NETWORK_MAP.get(fresh_order["network"].upper(), fresh_order["network"])
                            bg_bundles   = call_bundles_ghana(f"/bundles?network={network_name}")
                            if not bg_bundles.get("success"):
                                raise Exception(f"Bundles Ghana fetch failed: {bg_bundles.get('error')}")

                            bundle_volume = fresh_order["bundle"].upper().replace(" ", "")
                            matched = next(
                                (b for b in bg_bundles.get("bundles", [])
                                 if b.get("volume", "").upper().replace(" ", "") == bundle_volume
                                 and b.get("status") == "active"),
                                None
                            )
                            if not matched:
                                raise Exception(f"No active BG bundle for {network_name} {bundle_volume}")

                            bg_order = call_bundles_ghana("/order", method="POST", body={
                                "bundle_id":   matched["id"],
                                "phone":       fresh_order["phone_number"],
                                "webhook_url": "https://api.evosdata.xyz/webhook/bundlesghana"
                            })
                            if not bg_order.get("success"):
                                raise Exception(f"BG order failed: {bg_order.get('error', bg_order.get('message'))}")

                            supabase.table("orders").update({
                                "status":            "processing",
                                "datamart_ref":      bg_order["order"]["reference"],
                                "datamart_order_id": str(bg_order["order"]["id"])
                            }).eq("id", order_id).execute()
                            process_agent_profit(order_id, reference)
                            logger.info("ORDER PAYMENT RETRY: order %s dispatched to BUNDLES_GHANA ✅", order_id)

                        elif provider == "SWIFT_DATA_LINK":
                            volume = float(extract_capacity(fresh_order["bundle"]) or 0)
                            sdl = call_swift_data_link(
                                network=fresh_order["network"], volume=volume, phone=fresh_order["phone_number"]
                            )
                            if not sdl.get("success"):
                                raise Exception(f"SDL order failed: {sdl.get('error', sdl)}")
                            supabase.table("orders").update({
                                "status":            "processing",
                                "datamart_ref":      sdl.get("reference"),
                                "datamart_order_id": sdl.get("orderId"),
                            }).eq("id", order_id).execute()
                            process_agent_profit(order_id, reference)
                            logger.info("ORDER PAYMENT RETRY: order %s dispatched to SWIFT_DATA_LINK ✅", order_id)

                        elif provider == "AGYEKUMDATA":
                            package_id = get_agyekumdata_package_id(fresh_order["network"], fresh_order["bundle"])
                            safe_ref   = sanitise_agyekumdata_ref(reference)
                            agd        = call_agyekumdata_purchase(
                                package_id=package_id,
                                phone=fresh_order["phone_number"],
                                client_reference=reference,
                            )
                            if not agd.get("success"):
                                raise Exception(f"AGYEKUMDATA order failed: {agd.get('error', agd)}")
                            agd_data = agd.get("data", {})
                            supabase.table("orders").update({
                                "status":            "processing",
                                "datamart_ref":      agd_data.get("clientReference") or safe_ref,
                                "datamart_order_id": agd_data.get("orderId"),
                            }).eq("id", order_id).execute()
                            process_agent_profit(order_id, reference)
                            logger.info("ORDER PAYMENT RETRY: order %s dispatched to AGYEKUMDATA ✅", order_id)

                        else:
                            raise Exception("No provider assigned")

                    except Exception as dispatch_err:
                        logger.error("ORDER PAYMENT RETRY: dispatch error for order %s: %s", order_id, str(dispatch_err))
                        supabase.table("orders").update({"status": "failed"}).eq("id", order_id).execute()

                except Exception as e:
                    logger.error("ORDER PAYMENT RETRY: error verifying order %s: %s", order_id, str(e))

        except Exception as e:
            logger.error("ORDER PAYMENT RETRY ERROR: %s", str(e))

        await asyncio.sleep(300)



_checker_payment_retry_running = False

async def retry_stuck_checker_payments():
    global _checker_payment_retry_running
    if _checker_payment_retry_running:
        logger.info("CHECKER PAYMENT RETRY: already running, skipping duplicate")
        return

    _checker_payment_retry_running = True
    await asyncio.sleep(150)  # stagger vs the other three background jobs

    while True:
        try:
            logger.info("CHECKER PAYMENT RETRY: scanning for stuck checker payments...")

            now    = utc_now()
            floor  = (now - timedelta(minutes=5)).isoformat()
            cutoff = (now - timedelta(hours=6)).isoformat()

            stuck = supabase.table("checkers") \
                .select("*") \
                .in_("status", ["pending_payment", "failed"]) \
                .not_.is_("paystack_ref", None) \
                .is_("datamart_ref", None) \
                .lte("created_at", floor) \
                .gte("created_at", cutoff) \
                .execute()

            checkers = stuck.data or []
            logger.info("CHECKER PAYMENT RETRY: %d checker orders to check", len(checkers))

            for checker in checkers:
                checker_id = checker.get("id")
                reference  = checker.get("paystack_ref")

                if not reference or str(reference).startswith("CHK-AGT-"):
                    continue  # agent-buy checkers are wallet-debited, never touch Paystack

                try:
                    async with httpx.AsyncClient() as client:
                        res = await client.get(
                            f"https://api.paystack.co/transaction/verify/{reference}",
                            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"},
                            timeout=15,
                        )
                        data = res.json()

                    paystack_status = data.get("data", {}).get("status", "")
                    logger.info("CHECKER PAYMENT RETRY: checker %s ref=%s — Paystack status: %s", checker_id, reference, paystack_status)

                    if paystack_status != "success":
                        if checker["status"] == "pending_payment":
                            age = utc_now() - parse_db_dt(checker["created_at"])
                            if age > timedelta(minutes=30):
                                supabase.table("checkers").update({"status": "failed"}).eq("id", checker_id).execute()
                                logger.info("CHECKER PAYMENT RETRY: checker %s marked failed — unpaid after 30min", checker_id)
                        continue

                    recheck = supabase.table("checkers").select("*").eq("id", checker_id).limit(1).execute()
                    if not recheck.data:
                        continue
                    fresh = recheck.data[0]
                    if fresh["status"] not in ("pending_payment", "failed") or fresh.get("datamart_ref"):
                        logger.info("CHECKER PAYMENT RETRY: checker %s already advanced, skipping", checker_id)
                        continue

                    supabase.table("checkers").update({"status": "paid"}).eq("id", checker_id).execute()
                    logger.info("CHECKER PAYMENT RETRY: checker %s confirmed paid ✅", checker_id)

                    try:
                        fresh_paid = supabase.table("checkers").select("*").eq("id", checker_id).limit(1).execute().data[0]
                        dispatch_checker_order(fresh_paid)
                    except Exception as dispatch_err:
                        logger.error("CHECKER PAYMENT RETRY: dispatch error for checker %s: %s", checker_id, str(dispatch_err))
                        supabase.table("checkers").update({"status": "failed"}).eq("id", checker_id).execute()

                except Exception as e:
                    logger.error("CHECKER PAYMENT RETRY: error verifying checker %s: %s", checker_id, str(e))

        except Exception as e:
            logger.error("CHECKER PAYMENT RETRY ERROR: %s", str(e))

        await asyncio.sleep(300)


# =========================
# BACKGROUND: RETRY STUCK PAYSTACK WITHDRAWALS
# Two distinct kinds of "stuck" land here, both left at status "processing":
#
#  A) A transfer WAS created at Paystack (paystack_transfer_code is set) but
#     we never got a final transfer.success/failed webhook — re-verify it
#     directly with Paystack and finalize.
#
#  B) A transfer was NEVER created (paystack_transfer_code is null) —
#     almost always because our Paystack business balance was too low at
#     the moment the agent withdrew. The agent's wallet is already debited
#     and sitting frozen. We retry sending the transfer (safe/idempotent —
#     Paystack rejects a duplicate of the same reference rather than paying
#     twice) for up to WITHDRAWAL_RETRY_WINDOW_MINUTES in case the business
#     account gets topped up in the meantime. If it still hasn't gone
#     through after that window, we auto-refund the agent.
#
# All finalization goes through finalize_paystack_withdrawal(), which is
# gated on an atomic "status == processing" claim — so this job can never
# double-refund or double-pay even if it overlaps with the webhook, the
# agent's status-poll, or an admin action touching the same row.
# =========================
_withdrawal_retry_running = False
WITHDRAWAL_RETRY_WINDOW_MINUTES = 60   # keep trying to actually send it for up to 1hr
WITHDRAWAL_RETRY_MIN_AGE_MINUTES = 3   # give the normal flow / webhook a head start first

async def retry_stuck_paystack_withdrawals():
    global _withdrawal_retry_running
    if _withdrawal_retry_running:
        logger.info("WITHDRAWAL RETRY: already running, skipping duplicate")
        return

    _withdrawal_retry_running = True
    await asyncio.sleep(150)

    while True:
        try:
            logger.info("WITHDRAWAL RETRY: scanning for stuck paystack withdrawals...")

            now    = utc_now()
            floor  = (now - timedelta(minutes=WITHDRAWAL_RETRY_MIN_AGE_MINUTES)).isoformat()
            cutoff = (now - timedelta(hours=24)).isoformat()

            stuck = supabase.table("agent_withdrawals") \
                .select("*") \
                .eq("status", "processing") \
                .eq("provider", "paystack") \
                .lte("created_at", floor) \
                .gte("created_at", cutoff) \
                .execute()

            rows = stuck.data or []
            logger.info("WITHDRAWAL RETRY: %d stuck paystack withdrawals found", len(rows))

            for row in rows:
                withdrawal_id = row.get("id")
                try:
                    ref = row.get("paystack_ref")
                    if not ref:
                        continue

                    age = now - parse_db_dt(row["created_at"])
                    transfer_code = row.get("paystack_transfer_code")

                    # ── CASE A: transfer exists at Paystack, re-check it ──
                    if transfer_code:
                        result = paystack_verify_transfer(ref)
                        if not result.get("status"):
                            logger.info("WITHDRAWAL RETRY %s: verify failed: %s", withdrawal_id, result.get("message"))
                            continue
                        t_status = result.get("data", {}).get("status")
                        if t_status == "success":
                            finalize_paystack_withdrawal(row, "paid")
                        elif t_status in ("failed", "reversed"):
                            finalize_paystack_withdrawal(row, "failed", note=f"Paystack transfer {t_status}")
                        else:
                            logger.info("WITHDRAWAL RETRY %s: still '%s' at Paystack", withdrawal_id, t_status)
                        continue

                    # ── CASE B: never actually sent — retry within the window ──
                    if age > timedelta(minutes=WITHDRAWAL_RETRY_WINDOW_MINUTES):
                        finalize_paystack_withdrawal(
                            row, "failed",
                            note=f"Auto-refunded after {WITHDRAWAL_RETRY_WINDOW_MINUTES} min — payout could not be completed"
                        )
                        continue

                    network = (row.get("bank_name") or "").upper()
                    account_number = row.get("account_number")
                    if not network or not account_number:
                        logger.warning("WITHDRAWAL RETRY %s: missing network/account, cannot retry", withdrawal_id)
                        continue

                    recipient = paystack_create_recipient(
                        row.get("account_name") or "EVOS Agent", account_number, network
                    )
                    if not recipient.get("status"):
                        logger.info("WITHDRAWAL RETRY %s: recipient recreation failed: %s", withdrawal_id, recipient.get("message"))
                        continue

                    recipient_code = recipient["data"]["recipient_code"]
                    transfer = paystack_initiate_transfer(
                        amount=float(row["payout_amount"]),
                        recipient_code=recipient_code,
                        reference=ref,
                        reason=f"EVOS Agent Withdrawal #{withdrawal_id}",
                    )

                    if not transfer.get("status"):
                        msg = str(transfer.get("message", "") or "")
                        # A "duplicate reference" style response means Paystack
                        # already has a record of this transfer from a prior
                        # attempt — go verify its real status instead of
                        # treating this as a fresh failure.
                        if "duplicate" in msg.lower():
                            result = paystack_verify_transfer(ref)
                            if result.get("status"):
                                t_status = result.get("data", {}).get("status")
                                if t_status == "success":
                                    finalize_paystack_withdrawal(row, "paid")
                                elif t_status in ("failed", "reversed"):
                                    finalize_paystack_withdrawal(row, "failed", note=f"Paystack transfer {t_status}")
                        else:
                            supabase.table("agent_withdrawals").update({
                                "failure_reason": msg or "Paystack transfer could not be initiated"
                            }).eq("id", withdrawal_id).execute()
                            logger.info("WITHDRAWAL RETRY %s: still failing: %s", withdrawal_id, msg)
                        continue

                    tdata = transfer.get("data", {})
                    t_status = tdata.get("status")
                    supabase.table("agent_withdrawals").update({
                        "paystack_transfer_code": tdata.get("transfer_code"),
                    }).eq("id", withdrawal_id).execute()

                    if t_status == "success":
                        row["paystack_transfer_code"] = tdata.get("transfer_code")
                        finalize_paystack_withdrawal(row, "paid")
                        logger.info("WITHDRAWAL RETRY %s: succeeded on retry ✅", withdrawal_id)
                    else:
                        logger.info("WITHDRAWAL RETRY %s: now in flight at Paystack (status=%s)", withdrawal_id, t_status)

                except Exception as e:
                    logger.error("WITHDRAWAL RETRY: error on withdrawal %s: %s", withdrawal_id, str(e))

        except Exception as e:
            logger.error("WITHDRAWAL RETRY ERROR: %s", str(e))

        await asyncio.sleep(300)


async def startup_event():
    log_agyekumdata_categories()
    asyncio.create_task(retry_stuck_orders())
    asyncio.create_task(retry_stuck_deposits())
    asyncio.create_task(retry_stuck_order_payments())
    asyncio.create_task(retry_stuck_checker_payments())
    asyncio.create_task(retry_stuck_afa())
    asyncio.create_task(retry_stuck_paystack_withdrawals())
    asyncio.create_task(datamart_stock.poller_loop())


# =========================
# SPACEMAIL SMTP
# =========================

def _otp_log(msg, *args):
    """Print straight to stdout so it always shows in Render logs (root logging has a custom handler)."""
    try:
        print("[OTP] " + (msg % args if args else msg), flush=True)
    except Exception:
        print("[OTP] " + str(msg), flush=True)


def _mask_email(e: str) -> str:
    try:
        name, dom = e.split("@", 1)
        return f"{name[:2]}***@{dom}"
    except Exception:
        return "***"


def send_otp_email(to_email: str, otp: str, full_name: str) -> bool:
    if not SMTP_PASSWORD:
        _otp_log("OTP EMAIL: SMTP_PASSWORD env var is not set — cannot send to %s", _mask_email(to_email))
        return False

    from email.utils import formatdate, make_msgid

    msg = MIMEMultipart("alternative")
    msg["Subject"]    = "Your EvosHub password reset code"
    msg["From"]       = f"EvosHub Support <{SMTP_USER}>"
    msg["To"]         = to_email
    msg["Reply-To"]   = "support@evoshub.xyz"
    msg["Date"]       = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain="evoshub.xyz")

    text = (
        f"Hi {full_name},\n\n"
        f"Your EvosHub password reset code is: {otp}\n"
        f"It expires in 10 minutes.\n\n"
        f"If you didn't request this, you can ignore this email.\n\n"
        f"EvosHub Support - support@evoshub.xyz"
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;
                padding:24px;border:1px solid #eee;border-radius:8px;">
        <h2 style="color:#1a1a1a;">Password Reset</h2>
        <p>Hi <strong>{full_name}</strong>,</p>
        <p>
            Use the OTP below to reset your <strong>Evos password</strong>.
            This password is used across your EvosHub products and services
            by <strong>Evoxera Technology</strong>.
            The OTP expires in <strong>10 minutes</strong>.
        </p>
        <div style="font-size:36px;font-weight:bold;letter-spacing:8px;
                    text-align:center;padding:16px;background:#f4f4f4;
                    border-radius:6px;margin:24px 0;">
            {otp}
        </div>
        <p style="color:#888;font-size:13px;">
            If you didn't request this password reset, you can safely ignore
            this email. Your password won't change.
        </p>
        <p style="color:#888;font-size:13px;">
            Need help? support@evoshub.xyz<br>— Evoxera Technology Team
        </p>
    </div>
    """
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    # Try SSL (465) first, then STARTTLS (587) — some hosts block one of them.
    attempts = [(SMTP_HOST, SMTP_PORT, SMTP_PORT == 465)]
    if SMTP_PORT == 465:
        attempts.append((SMTP_HOST, 587, False))
    last_err = None
    for host, port, use_ssl in attempts:
        try:
            if use_ssl:
                server = smtplib.SMTP_SSL(host, port, timeout=15)
            else:
                server = smtplib.SMTP(host, port, timeout=15)
                server.ehlo()
                server.starttls()
                server.ehlo()
            with server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                refused = server.sendmail(SMTP_USER, [to_email], msg.as_string())
            if refused:
                _otp_log("OTP EMAIL: recipient refused %s: %s", _mask_email(to_email), refused)
                return False
            _otp_log("OTP EMAIL: sent to %s via %s:%s", _mask_email(to_email), host, port)
            return True
        except Exception as e:
            last_err = e
            _otp_log("OTP EMAIL: SMTP failure via %s:%s: %r", host, port, e)
    _otp_log("OTP EMAIL: all SMTP attempts failed for %s: %r", _mask_email(to_email), last_err)
    return False

# =========================
# ORDERS
# =========================
@router.get("/orders/me")
@limiter.limit("30/minute")
def get_user_orders(request: Request, user_id: int = Query(...)):
    require_user(request, user_id)  # token must belong to this user_id
    try:
        orders = supabase.table("orders").select("*").eq("user_id", user_id).execute()
        return {"status": "success", "orders": orders.data or []}
    except Exception as e:
        logger.error("GET ORDERS ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch orders")

@router.get("/orders/track")
@limiter.limit("20/minute")
def track_orders(request: Request, phone: str = Query(...)):
    try:
        cleaned = normalise_phone(phone)
        orders = supabase.table("orders") \
            .select("network, bundle, price, phone_number, status, created_at, evosdata_ref, paystack_ref") \
            .eq("phone_number", cleaned) \
            .order("created_at", desc=True) \
            .limit(10) \
            .execute()
        return {"orders": orders.data or []}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("TRACK ERROR: %s", str(e))
        raise HTTPException(500, "Failed to fetch orders")

@router.post("/orders/create")
@limiter.limit("10/minute")
def create_order(request: Request, data: CreateOrderRequest):
    try:
        data.user_id = resolve_order_identity(request, data.user_id)
        if not datamart_stock.bundle_in_stock(data.network, data.bundle):
            raise HTTPException(400, datamart_stock.OUT_OF_STOCK_MESSAGE)

        buyer_key = data.user_id if data.user_id else data.email

        if buyer_key:
            query = supabase.table("orders").select("id, created_at, paystack_ref, network, bundle, price, phone_number")
            if data.user_id:
                query = query.eq("user_id", data.user_id)
            else:
                query = query.eq("guest_email", data.email)

            existing = query \
                .eq("network", data.network) \
                .eq("bundle", data.bundle) \
                .eq("status", "pending_payment") \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()

            if existing.data:
                order = existing.data[0]
                created_at = parse_db_dt(order["created_at"])
                if utc_now() - created_at < timedelta(minutes=10):
                    if data.user_id:
                        user_res = supabase.table("users").select("email").eq("id", data.user_id).limit(1).execute()
                        customer_email = user_res.data[0]["email"] if user_res.data else "guest@evoshub.com"
                    else:
                        customer_email = data.email or "guest@evoshub.com"

                    new_ref = f"{order['paystack_ref']}-R{uuid.uuid4().hex[:4].upper()}"
                    try:
                        paystack = requests.post(
                            "https://api.paystack.co/transaction/initialize",
                            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
                            json={
                                "email": customer_email,
                                "amount": int(float(order["price"]) * 100),
                                "reference": new_ref,
                                "callback_url": f"{callback_base(request)}/success",
                            },
                            timeout=REQUEST_TIMEOUT
                        ).json()
                    except requests.exceptions.RequestException:
                        raise HTTPException(500, "Payment service error")

                    if not paystack.get("status"):
                        raise HTTPException(400, "Payment reinit failed")

                    supabase.table("orders").update({"paystack_ref": new_ref}).eq("id", order["id"]).execute()

                    return {
                        "status": True,
                        "pending": True,
                        "message": f"Pending {order['bundle']} {order['network']} order found. Redirecting to payment...",
                        "reference": new_ref,
                        "payment_url": paystack["data"]["authorization_url"],
                    }

        price_res = supabase.table("prices").select("price").eq("network", data.network).eq("bundle", data.bundle).limit(1).execute()
        if not price_res.data:
            raise HTTPException(400, "Invalid bundle")

        price = float(price_res.data[0]["price"])

        customer_email = None
        if data.user_id:
            user_res = supabase.table("users").select("email").eq("id", data.user_id).limit(1).execute()
            if not user_res.data:
                raise HTTPException(404, "User not found")
            customer_email = user_res.data[0]["email"]
        else:
            customer_email = data.email

        if not customer_email:
            customer_email = "guest@evoshub.com"

        callback_url = f"{callback_base(request)}/success"

        try:
            paystack = requests.post(
                "https://api.paystack.co/transaction/initialize",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
                json={"email": customer_email, "amount": int(price * 100), "callback_url": callback_url},
                timeout=REQUEST_TIMEOUT
            ).json()
        except requests.exceptions.RequestException:
            raise HTTPException(500, "Payment service error")

        if not paystack.get("status"):
            raise HTTPException(400, "Payment init failed")

        ref      = paystack["data"]["reference"]
        evos_ref = f"EVOS-{uuid.uuid4().hex[:8].upper()}"

        payload = {
            "user_id":      data.user_id,
            "guest_email":  None if data.user_id else customer_email,
            "network":      data.network,
            "bundle":       data.bundle,
            "price":        price,
            "phone_number": data.phone,
            "paystack_ref": ref,
            "evosdata_ref": evos_ref,
            "status":       "pending_payment"
        }
        supabase.table("orders").insert(payload).execute()

        return {"status": True, "payment_url": paystack["data"]["authorization_url"], "reference": ref}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("CREATE ORDER ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Server error")


# =========================
# PAYSTACK WEBHOOK
# =========================
@router.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    try:
        body      = await request.body()
        signature = request.headers.get("x-paystack-signature")

        if not signature or not verify_signature(body, signature, PAYSTACK_SECRET):
            logger.warning("PAYSTACK WEBHOOK: invalid signature from %s", request.client.host)
            print(f"PAYSTACK WEBHOOK: invalid signature from {request.client.host}")
            return {"status": "invalid signature"}

        payload = await request.json()
        event   = payload.get("event")

        # =========================
        # EVENT: charge.success
        # =========================
        if event == "charge.success":

            reference = payload["data"]["reference"]
            print(f"PAYSTACK WEBHOOK: charge.success received, reference={reference}")

            # ── CHECKER ORDER? ───────────────────────────────────────────
            checker_res = supabase.table("checkers").select("*").eq("paystack_ref", reference).limit(1).execute()
            if checker_res.data:
                checker = checker_res.data[0]

                if checker["status"] != "pending_payment":
                    print(f"PAYSTACK WEBHOOK: checker {checker['id']} already processed (status={checker['status']})")
                    return {"status": "already processed"}

                supabase.table("checkers").update({"status": "paid"}).eq("paystack_ref", reference).execute()
                print(f"PAYSTACK WEBHOOK: checker {checker['id']} marked as paid")

                try:
                    fresh = supabase.table("checkers").select("*").eq("id", checker["id"]).limit(1).execute().data[0]
                    dispatch_checker_order(fresh)
                    print(f"PAYSTACK WEBHOOK: checker {checker['id']} dispatched successfully ✅")
                    return {"status": "success"}
                except Exception as e:
                    logger.error("CHECKER DISPATCH ERROR: %s", str(e))
                    print(f"CHECKER DISPATCH ERROR: {str(e)}")
                    # Payment already confirmed — mark "failed" (not left as "paid")
                    # so retry_stuck_checker_payments() picks it up on the next cycle,
                    # since that job only scans status in ("pending_payment", "failed").
                    supabase.table("checkers").update({"status": "failed"}).eq("id", checker["id"]).execute()
                    return {"status": "checker dispatch failed"}

            # ── AFA REGISTRATION? ────────────────────────────────────────
            afa_res = supabase.table("afa_registrations").select("*").eq("paystack_ref", reference).limit(1).execute()
            if afa_res.data:
                afa = afa_res.data[0]
                if afa["status"] != "pending_payment":
                    return {"status": "already processed"}
                await asyncio.to_thread(mark_afa_paid_and_dispatch, afa)
                return {"status": "success"}

            # ── DATA ORDER (existing logic, unchanged) ────────────────────
            order_res = supabase.table("orders").select("*").eq("paystack_ref", reference).limit(1).execute()
            if not order_res.data:
                print(f"PAYSTACK WEBHOOK: no order found for reference={reference}")
                return {"status": "not found"}

            order = order_res.data[0]
            if order["status"] != "pending_payment":
                print(f"PAYSTACK WEBHOOK: order {order['id']} already processed (status={order['status']})")
                return {"status": "already processed"}

            supabase.table("orders").update({"status": "paid"}).eq("paystack_ref", reference).execute()
            print(f"PAYSTACK WEBHOOK: order {order['id']} marked as paid")

            if order.get("user_id"):
                increment_user_orders(order["user_id"])

            provider = get_provider(order["network"])
            print(f"PAYSTACK WEBHOOK: resolved provider={provider} for network={order['network']}")

            try:
                if provider == "DATAMART":
                    dm_response = datamart_stock.purchase_post(
                        f"{DATAMART_BASE}/purchase",
                        headers={"X-API-Key": DATAMART_API_KEY},
                        json={
                            "phoneNumber": order["phone_number"],
                            "network": NETWORK_MAP.get(order["network"]),
                            "capacity": extract_capacity(order["bundle"]),
                            "gateway": "wallet"
                        },
                        timeout=REQUEST_TIMEOUT
                    )
                    dm = dm_response.json()
                    dm_data = dm.get("data", {})
                    supabase.table("orders").update({
                        "status": "processing",
                        "datamart_ref": dm_data.get("orderReference"),
                        "datamart_order_id": dm_data.get("orderId")
                    }).eq("paystack_ref", reference).execute()
                    process_agent_profit(order["id"], reference)
                    print(f"PAYSTACK WEBHOOK: order {order['id']} dispatched to DATAMART orderId={dm_data.get('orderId')}")

                elif provider == "BUNDLES_GHANA":
                    BG_NETWORK_MAP = {"MTN": "MTN", "TELECEL": "Telecel", "AIRTELTIGO": "AirtelTigo", "AT": "AirtelTigo"}
                    network_name = BG_NETWORK_MAP.get(order["network"].upper(), order["network"])
                    bg_bundles = call_bundles_ghana(f"/bundles?network={network_name}")
                    if not bg_bundles.get("success"):
                        raise Exception(f"Bundles Ghana fetch failed: {bg_bundles.get('error')}")

                    bundle_volume = order["bundle"].upper().replace(" ", "")
                    matched = next(
                        (b for b in bg_bundles.get("bundles", [])
                         if b.get("volume", "").upper().replace(" ", "") == bundle_volume
                         and b.get("status") == "active"),
                        None
                    )
                    if not matched:
                        raise Exception(f"No active BG bundle for {network_name} {bundle_volume}")

                    bg_order = call_bundles_ghana("/order", method="POST", body={
                        "bundle_id": matched["id"],
                        "phone": order["phone_number"],
                        "webhook_url": "https://api.evosdata.xyz/webhook/bundlesghana"
                    })
                    if not bg_order.get("success"):
                        raise Exception(f"BG order failed: {bg_order.get('error', bg_order.get('message'))}")

                    supabase.table("orders").update({
                        "status": "processing",
                        "datamart_ref": bg_order["order"]["reference"],
                        "datamart_order_id": str(bg_order["order"]["id"])
                    }).eq("paystack_ref", reference).execute()
                    process_agent_profit(order["id"], reference)
                    print(f"PAYSTACK WEBHOOK: order {order['id']} dispatched to BUNDLES_GHANA orderId={bg_order['order']['id']}")

                elif provider == "SWIFT_DATA_LINK":
                    volume = float(extract_capacity(order["bundle"]) or 0)
                    sdl = call_swift_data_link(network=order["network"], volume=volume, phone=order["phone_number"])
                    if not sdl.get("success"):
                        raise Exception(f"SDL order failed: {sdl.get('error', sdl)}")
                    supabase.table("orders").update({
                        "status": "processing",
                        "datamart_ref": sdl.get("reference"),
                        "datamart_order_id": sdl.get("orderId"),
                    }).eq("paystack_ref", reference).execute()
                    process_agent_profit(order["id"], reference)
                    print(f"PAYSTACK WEBHOOK: order {order['id']} dispatched to SWIFT_DATA_LINK orderId={sdl.get('orderId')}")

                elif provider == "AGYEKUMDATA":
                    package_id = get_agyekumdata_package_id(order["network"], order["bundle"])
                    safe_ref   = sanitise_agyekumdata_ref(reference)
                    agd        = call_agyekumdata_purchase(
                        package_id=package_id,
                        phone=order["phone_number"],
                        client_reference=reference,
                    )
                    if not agd.get("success"):
                        raise Exception(f"AGYEKUMDATA order failed: {agd.get('error', agd)}")
                    agd_data = agd.get("data", {})
                    supabase.table("orders").update({
                        "status":            "processing",
                        "datamart_ref":      agd_data.get("clientReference") or safe_ref,
                        "datamart_order_id": agd_data.get("orderId"),
                    }).eq("paystack_ref", reference).execute()
                    process_agent_profit(order["id"], reference)
                    logger.info(
                        "PAYSTACK WEBHOOK: order %s dispatched to AGYEKUMDATA orderId=%s ✅",
                        order['id'], agd_data.get("orderId")
                    )
                    print(f"PAYSTACK WEBHOOK: order {order['id']} dispatched to AGYEKUMDATA orderId={agd_data.get('orderId')}")

                else:
                    raise Exception("No provider assigned")

                return {"status": "success"}

            except Exception as e:
                logger.error("PURCHASE ERROR: %s", str(e))
                print(f"PURCHASE ERROR: {str(e)}")
                supabase.table("orders").update({"status": "failed"}).eq("paystack_ref", reference).execute()
                return {"status": "purchase failed"}

        # =========================
        # EVENT: transfer.success / transfer.failed / transfer.reversed
        # (agent withdrawal payout status updates)
        # =========================
        elif event in ("transfer.success", "transfer.failed", "transfer.reversed"):

            data      = payload.get("data", {})
            reference = data.get("reference")

            print(f"PAYSTACK WEBHOOK: {event} received, reference={reference}")

            if not reference:
                print("PAYSTACK WEBHOOK: transfer event missing reference, ignoring")
                return {"status": "ignored"}

            wd = supabase.table("agent_withdrawals").select("*").eq("paystack_ref", reference).limit(1).execute()
            if not wd.data:
                print(f"PAYSTACK WEBHOOK: no agent_withdrawals row found for reference={reference}")
                return {"status": "not found"}

            row          = wd.data[0]
            final_status = "paid" if event == "transfer.success" else "failed"
            note         = None if final_status == "paid" else f"Paystack {event} webhook"

            # Atomic — the same helper the retry job and status-poll
            # endpoint use, so no matter which one gets there first, only
            # one actually applies the wallet refund / debit record.
            applied = finalize_paystack_withdrawal(row, final_status, note=note)
            if not applied:
                print(f"PAYSTACK WEBHOOK: withdrawal {row.get('id')} already finalized, skipping")
                return {"status": "already processed"}

            print(f"PAYSTACK WEBHOOK: withdrawal {row.get('id')} updated to status={final_status}")
            return {"status": "processed"}

        # =========================
        # EVENT: anything else — ignore
        # =========================
        else:
            print(f"PAYSTACK WEBHOOK: ignored event type={event}")
            return {"status": "ignored"}

    except Exception as e:
        logger.error("PAYSTACK WEBHOOK ERROR: %s", str(e))
        print(f"PAYSTACK WEBHOOK ERROR: {str(e)}")
        return {"status": "error"}

# =========================
# DATAMART WEBHOOK
# =========================
@router.post("/webhook/datamart")
async def datamart_webhook(request: Request):
    try:
        body      = await request.body()
        signature = request.headers.get("X-DataMart-Signature")
        event     = request.headers.get("X-DataMart-Event", "")

        if not signature or not verify_datamart_signature(body, signature, DATAMART_WEBHOOK_SECRET):
            raise HTTPException(401, "Invalid signature")

        payload   = await request.json()
        data      = payload.get("data", {})
        order_ref = data.get("orderReference") or data.get("reference")
        order_id  = data.get("orderId")
        status    = str(data.get("status", "")).lower()

        logger.info("DATAMART EVENT: %s", event)
        logger.info("DATAMART REF: %s", order_ref)
        logger.info("DATAMART ORDER ID: %s", order_id)
        logger.info("DATAMART STATUS: %s", status)

        if not order_ref and not order_id:
            return {"received": True}

        final_status = (
            "successful" if status in ["completed", "success", "delivered"]
            else "failed" if status in ["failed", "cancelled", "refunded"]
            else "processing"
        )

        if order_ref:
            supabase.table("orders").update({"status": final_status}).eq("datamart_ref", order_ref).execute()
            logger.info("DATAMART WEBHOOK: updated by datamart_ref=%s → %s", order_ref, final_status)
        elif order_id:
            supabase.table("orders").update({"status": final_status}).eq("datamart_order_id", str(order_id)).execute()
            logger.info("DATAMART WEBHOOK: updated by order_id=%s → %s", order_id, final_status)

        return {"received": True}

    except HTTPException as e:
        logger.warning("DATAMART WEBHOOK AUTH ERROR: %s", str(e.detail))
        raise e
    except Exception as e:
        logger.error("DATAMART WEBHOOK ERROR: %s", str(e))
        return {"received": False}



@router.post("/webhook/datamart-checkers")
async def datamart_checkers_webhook(request: Request):
    try:
        body      = await request.body()
        signature = request.headers.get("X-DataMart-Signature")

        if not signature or not verify_datamart_signature(body, signature, DATAMART_WEBHOOK_SECRET):
            raise HTTPException(401, "Invalid signature")

        payload = await request.json()
        data    = payload.get("data", {})
        ref     = data.get("reference")

        if not ref:
            return {"received": True}

        checker_res = supabase.table("checkers").select("*").eq("datamart_ref", ref).limit(1).execute()
        if not checker_res.data:
            return {"received": True}

        checker = checker_res.data[0]
        card = {
            "purchaseId":   data.get("purchaseId"),
            "reference":    ref,
            "serialNumber": data.get("serialNumber"),
            "pin":          data.get("pin"),
            "price":        data.get("price"),
            "createdAt":    data.get("createdAt"),
        }
        existing_cards = checker.get("serial_numbers") or []
        if not any(c.get("reference") == ref for c in existing_cards):
            existing_cards.append(card)

        supabase.table("checkers").update({
            "status":         "successful",
            "serial_numbers": existing_cards,
        }).eq("id", checker["id"]).execute()

        return {"received": True}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error("DATAMART CHECKERS WEBHOOK ERROR: %s", str(e))
        return {"received": False}


# =========================
# BUNDLES GHANA WEBHOOK
# =========================
@router.post("/webhook/bundlesghana")
async def bundlesghana_webhook(request: Request):
    try:
        payload   = await request.json()
        event     = payload.get("event", "")
        reference = payload.get("reference")
        status    = str(payload.get("status", "")).lower()

        logger.info("BUNDLES GHANA EVENT: %s", event)
        logger.info("BUNDLES GHANA REF: %s", reference)
        logger.info("BUNDLES GHANA STATUS: %s", status)

        if not reference:
            return {"received": True}

        final_status = (
            "successful" if status in ["delivered"]
            else "processing" if status in ["placed", "processing"]
            else "failed" if status in ["failed", "cancelled", "refunded"]
            else "processing"
        )
        supabase.table("orders").update({"status": final_status}).eq("datamart_ref", reference).execute()
        return {"received": True}
    except Exception as e:
        logger.error("BUNDLES GHANA WEBHOOK ERROR: %s", str(e))
        return {"received": False}


# =========================
# SWIFT DATA LINK WEBHOOK
# =========================
@router.post("/webhook/swiftdatalink")
async def swiftdatalink_webhook(request: Request):
    try:
        payload   = await request.json()
        event     = payload.get("event", "")
        order_id  = payload.get("orderId", "")
        reference = payload.get("reference", "")
        status    = str(payload.get("status", "")).lower()

        if str(event).lower().startswith("afa") or payload.get("registration") or payload.get("registrationId"):
            reg    = payload.get("registration") or payload.get("data") or payload
            reg_id = reg.get("registrationId") or reg.get("id") or payload.get("registrationId")
            if not reg_id:
                return {"received": True}
            rows = supabase.table("afa_registrations").select("*").eq("sdl_registration_id", str(reg_id)).limit(1).execute().data
            if not rows:
                # webhook can beat our DB write of the id — match on our own idempotency reference/phone
                ref = reg.get("reference") or reg.get("idempotencyKey")
                if ref:
                    rows = supabase.table("afa_registrations").select("*").eq("evosdata_ref", str(ref)).limit(1).execute().data
            if not rows:
                logger.warning("SDL AFA WEBHOOK: no registration for %s", reg_id)
                return {"received": True}
            row = rows[0]
            new_status = map_afa_status(reg.get("status") or payload.get("status"))
            reason = str(reg.get("rejectionReason") or reg.get("reason") or payload.get("reason") or "Rejected by provider")
            if not row.get("sdl_registration_id"):
                supabase.table("afa_registrations").update({"sdl_registration_id": str(reg_id)}).eq("id", row["id"]).execute()
            if new_status == "rejected" and row.get("agent_id"):
                refund_agent_afa(row, reason)
            elif new_status != row["status"] and row["status"] != "rejected":
                supabase.table("afa_registrations").update({
                    "status": new_status, "provider_status": str(reg.get("status") or payload.get("status")),
                    "failure_reason": reason[:300] if new_status == "rejected" else None,
                    "updated_at": utc_now().isoformat(),
                }).eq("id", row["id"]).execute()
            logger.info("SDL AFA WEBHOOK: %s → %s", reg_id, new_status)
            return {"received": True}

        logger.info("SDL WEBHOOK EVENT: %s", event)
        logger.info("SDL WEBHOOK ORDER ID: %s", order_id)
        logger.info("SDL WEBHOOK REFERENCE: %s", reference)
        logger.info("SDL WEBHOOK STATUS: %s", status)

        if not order_id and not reference:
            return {"received": True}

        final_status = (
            "successful" if status in ["delivered", "resolved"]
            else "failed" if status in ["failed", "cancelled", "refunded"]
            else "processing"
        )

        if reference:
            supabase.table("orders").update({"status": final_status}).eq("datamart_ref", reference).execute()
            logger.info("SDL WEBHOOK: updated by reference=%s → %s", reference, final_status)
        elif order_id:
            supabase.table("orders").update({"status": final_status}).eq("datamart_order_id", order_id).execute()
            logger.info("SDL WEBHOOK: updated by orderId=%s → %s", order_id, final_status)

        return {"received": True}
    except Exception as e:
        logger.error("SDL WEBHOOK ERROR: %s", str(e))
        return {"received": False}


# =========================
# AGYEKUMDATA WEBHOOK
# =========================
@router.post("/webhook/agyekumdata")
async def agyekumdata_webhook(request: Request):
    try:
        body      = await request.body()
        signature = request.headers.get("X-AGYEKUMDATA-SIGNATURE", "")

        if not verify_agyekumdata_signature(body, signature):
            logger.warning(
                "AGYEKUMDATA WEBHOOK: invalid signature from %s",
                request.client.host
            )
            return {"received": False, "reason": "invalid signature"}

        payload  = await request.json()
        event    = payload.get("event", "")
        order_id = payload.get("orderId", "")
        status   = str(payload.get("status", "")).upper()

        logger.info(
            "AGYEKUMDATA WEBHOOK EVENT=%s ORDER_ID=%s STATUS=%s",
            event, order_id, status
        )

        if event != "ORDER_STATUS_UPDATED":
            logger.info("AGYEKUMDATA WEBHOOK: ignoring event %s", event)
            return {"received": True}

        if not order_id:
            logger.warning("AGYEKUMDATA WEBHOOK: no orderId in payload")
            return {"received": True}

        final_status = (
            "successful" if status in ["SUCCESS", "COMPLETED", "DELIVERED"]
            else "failed"  if status in ["FAILED", "CANCELLED", "REJECTED"]
            else "processing"
        )

        result = supabase.table("orders") \
            .update({"status": final_status}) \
            .eq("datamart_order_id", order_id) \
            .execute()

        if result.data:
            logger.info(
                "AGYEKUMDATA WEBHOOK: updated %d row(s) by orderId=%s → %s",
                len(result.data), order_id, final_status
            )
        else:
            fallback = supabase.table("orders") \
                .update({"status": final_status}) \
                .eq("datamart_ref", order_id) \
                .execute()
            logger.info(
                "AGYEKUMDATA WEBHOOK: fallback updated %d row(s) by datamart_ref=%s → %s",
                len(fallback.data or []), order_id, final_status
            )

        return {"received": True}

    except Exception as e:
        logger.error("AGYEKUMDATA WEBHOOK ERROR: %s", str(e))
        return {"received": False}


# =========================
# SYNC ORDER
# =========================
@router.post("/orders/sync/{reference}")
@limiter.limit("20/minute")
def sync_order(request: Request, reference: str):
    try:
        order_res = supabase.table("orders").select("*").eq("paystack_ref", reference).limit(1).execute()
        if not order_res.data:
            raise HTTPException(404, "Order not found")

        order    = order_res.data[0]
        tracker  = order.get("datamart_order_id") or order.get("datamart_ref")
        if not tracker:
            return {"status": "not processed yet"}

        provider = get_provider(order["network"])

        if provider == "DATAMART":
            dm = requests.get(
                f"{DATAMART_BASE}/order-status/{tracker}",
                headers={"X-API-Key": DATAMART_API_KEY},
                timeout=REQUEST_TIMEOUT
            )
            dm.raise_for_status()
            payload = dm.json()
            status = str(payload.get("data", {}).get("orderStatus", "")).lower()

        elif provider == "BUNDLES_GHANA":
            bg_ref = order.get("datamart_ref")
            if not bg_ref:
                status = order["status"].lower()
            else:
                bg = call_bundles_ghana(f"/order/status/{bg_ref}")
                status = str(bg.get("order", {}).get("status", "processing")).lower()

        elif provider == "SWIFT_DATA_LINK":
            sdl_res = requests.get(
                f"{SWIFT_DATA_LINK_BASE}/order/status/{tracker}",
                headers={"x-api-key": SWIFT_DATA_LINK_API_KEY},
                timeout=REQUEST_TIMEOUT
            ).json()
            status = str(sdl_res.get("order", {}).get("status", "processing")).lower()

        elif provider == "AGYEKUMDATA":
            client_ref = order.get("datamart_ref") or tracker
            agd_res = call_agyekumdata_status(client_reference=client_ref)
            status = str(agd_res.get("data", {}).get("status", "processing")).lower()
            logger.info("SYNC ORDER: AGYEKUMDATA clientRef=%s status=%s", client_ref, status)

        else:
            status = "processing"

        final_status = (
            "successful" if status in ["completed", "success", "delivered", "successful", "resolved"]
            else "failed" if status in ["failed", "cancelled", "refunded"]
            else "processing"
        )
        supabase.table("orders").update({"status": final_status}).eq("paystack_ref", reference).execute()
        return {"status": final_status}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error("SYNC ERROR: %s", str(e))
        raise HTTPException(500, "Sync failed")


# =========================
# USER PROFILE
# =========================
@router.get("/users/me")
@limiter.limit("30/minute")
def get_user(request: Request, user_id: int):
    require_user(request, user_id)  # token must belong to this user_id
    try:
        res = supabase.table("users").select("*").eq("id", user_id).single().execute()
        user = res.data
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user_data = {
            "id":           user.get("id"),
            "username":     user.get("username"),
            "email":        user.get("email"),
            "full_name":    user.get("full_name"),
            "role":         user.get("role", "user"),
            "agent_status": user.get("agent_status", "pending"),
            "rank":         user.get("rank", 1),
            "referral_code": user.get("referral_code", ""),
        }
        return {"status": "success", "user": user_data}
    except Exception as e:
        logger.error("GET USER ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch user")


# =========================
# AGENT DASHBOARD
# =========================
@router.get("/agent/dashboard/{agent_id}")
@limiter.limit("30/minute")
async def agent_dashboard(request: Request, agent_id: int, _: int = Depends(require_agent)):
    user = supabase.table("users").select("role, agent_status").eq("id", agent_id).limit(1).execute()
    if not user.data:
        return {"error": "User not found"}
    u = user.data[0]
    if u["role"] != "agent" or u["agent_status"] != "approved":
        return {"error": "Not authorized"}

    wallet = supabase.table("agent_wallets").select("*").eq("agent_id", agent_id).limit(1).execute()
    balance = wallet.data[0]["balance"] if wallet.data else 0

    transactions = supabase.table("agent_transactions").select("*").eq("agent_id", agent_id).execute()
    total_earned = sum(t["amount"] for t in transactions.data) if transactions.data else 0

    orders = supabase.table("orders").select("id", count="exact").eq("agent_id", agent_id).execute()

    return {
        "wallet_balance":     balance,
        "total_earned":       total_earned,
        "total_sales":        orders.count if hasattr(orders, "count") else len(orders.data or []),
        "transactions_count": len(transactions.data or [])
    }


@router.get("/agent/wallet/{agent_id}")
@limiter.limit("30/minute")
async def get_wallet(request: Request, agent_id: int, _: int = Depends(require_agent)):
    wallet = supabase.table("agent_wallets").select("*").eq("agent_id", agent_id).limit(1).execute()
    if not wallet.data:
        return {"agent_id": agent_id, "balance": 0}
    return wallet.data[0]


@router.get("/agent/transactions/{agent_id}")
@limiter.limit("30/minute")
async def agent_transactions(request: Request, agent_id: int, _: int = Depends(require_agent)):
    res = supabase.table("agent_transactions") \
        .select("*") \
        .eq("agent_id", agent_id) \
        .order("created_at", desc=True) \
        .limit(50) \
        .execute()
    return {"transactions": res.data or []}


@router.get("/agent/sales/{agent_id}")
@limiter.limit("30/minute")
async def agent_sales(request: Request, agent_id: int, _: int = Depends(require_agent)):
    orders = supabase.table("orders") \
        .select("id, agent_price, base_price, created_at") \
        .eq("agent_id", agent_id) \
        .execute()
    data = orders.data or []
    total_profit = sum(
        (o["agent_price"] - o["base_price"])
        for o in data
        if o.get("agent_price") and o.get("base_price")
    )
    return {"total_orders": len(data), "total_profit": total_profit}


# =========================
# AGENT WITHDRAW
# NOTE: "Enable OTP for transfers" must be OFF in the Paystack dashboard
#       (Settings -> Preferences) for this flow to work correctly. That
#       setting sends the OTP to the phone/email registered on the
#       business's Paystack account — NOT to the agent or the transfer
#       recipient — so agents have no way to receive or enter it. With
#       OTP disabled, /transfer returns "success" or "pending" directly
#       and the payout completes without any manual step.
# =========================
@router.get("/agent/withdraw/fee-info")
@limiter.limit("30/minute")
def get_withdraw_fee_info(request: Request):
    return {"fee_percent": WITHDRAWAL_FEE_PERCENT}


@router.post("/agent/withdraw")
@limiter.limit("5/minute")
async def request_withdrawal(request: Request, payload: WithdrawRequest):
    token = request.headers.get("X-Agent-Token", "")
    if not token or not verify_agent_token(token, payload.agent_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    agent_id      = payload.agent_id
    amount        = float(payload.amount)
    mobile_number = payload.mobile_number
    network       = payload.network.upper()
    account_name  = payload.account_name or ""
    provider      = payload.provider  # "paystack" or "moolre", chosen on step 1

    wallet = supabase.table("agent_wallets").select("balance").eq("agent_id", agent_id).limit(1).execute()
    if not wallet.data:
        return {"error": "Wallet not found"}

    balance = float(wallet.data[0]["balance"])
    if amount > balance:
        return {"error": "Insufficient balance"}
    if amount < 5:
        return {"error": "Minimum withdrawal is GH₵5"}

    new_balance = round(balance - amount, 2)
    supabase.table("agent_wallets").update({"balance": new_balance}).eq("agent_id", agent_id).execute()

    def refund():
        supabase.table("agent_wallets").update({"balance": balance}).eq("agent_id", agent_id).execute()

    fee, payout_amount = calc_withdrawal_fee(amount)

    # ── PAYSTACK PATH ───────────────────────────────────────────
    if provider == "paystack":
        if network not in PAYSTACK_MOMO_BANK_CODE:
            refund()
            return {"error": f"Unsupported network for Paystack: {network}"}

        paystack_ref = f"evos-wd-{agent_id}-{uuid.uuid4().hex[:12]}"

        wd = supabase.table("agent_withdrawals").insert({
            "agent_id":       agent_id,
            "amount":         amount,
            "fee":            fee,
            "payout_amount":  payout_amount,
            "account_name":   account_name,
            "account_number": mobile_number,
            "bank_name":      network,
            "status":         "processing",
            "provider":       "paystack",
            "paystack_ref":   paystack_ref,
        }).execute()

        if not wd.data:
            refund()
            return {"error": "Failed to create withdrawal record"}

        withdrawal_id = wd.data[0]["id"]

        # If the frontend didn't already pass a resolved name (e.g. the
        # agent skipped or bypassed the verify-account step), resolve it
        # here too rather than silently falling back to "EVOS Agent".
        resolved_account_name = account_name
        if not resolved_account_name:
            resolved = paystack_resolve_account(mobile_number, PAYSTACK_MOMO_BANK_CODE.get(network, ""))
            if resolved.get("status"):
                resolved_account_name = resolved.get("data", {}).get("account_name", "") or ""
            else:
                logger.warning(
                    "PAYSTACK RESOLVE (withdraw): could not resolve %s on %s: %s",
                    mobile_number, network, resolved.get("message")
                )

        recipient = paystack_create_recipient(resolved_account_name or "EVOS Agent", mobile_number, network)
        if not recipient.get("status"):
            refund()
            supabase.table("agent_withdrawals").update({"status": "failed"}).eq("id", withdrawal_id).execute()
            return {"error": recipient.get("message", "Could not create transfer recipient")}

        if resolved_account_name and resolved_account_name != account_name:
            supabase.table("agent_withdrawals").update({"account_name": resolved_account_name}).eq("id", withdrawal_id).execute()

        recipient_code = recipient["data"]["recipient_code"]
        # NOTE: only the post-fee amount is actually transferred. The agent's
        # wallet was already debited the full `amount` above.
        transfer = paystack_initiate_transfer(
            amount=payout_amount,
            recipient_code=recipient_code,
            reference=paystack_ref,
            reason=f"EVOS Agent Withdrawal #{withdrawal_id}",
        )

        if not transfer.get("status"):
            transfer_msg = str(transfer.get("message", "") or "")

            # ANY failure to initiate a transfer at this point — insufficient
            # business balance, account restrictions, rate limits, whatever
            # Paystack's exact wording happens to be — is an internal/ops
            # problem, never something the agent caused or can fix. We NEVER
            # surface Paystack's raw message to the agent (wording changes
            # over time and keyword-matching for it is fragile — safer to
            # just never show any of it).
            #
            # We also don't refund immediately: the wallet stays debited and
            # the request stays "processing". retry_stuck_paystack_withdrawals()
            # (background job) will keep retrying the transfer for up to an
            # hour in case it was just a temporary low-balance situation, and
            # will auto-refund the agent if it still can't go through after
            # that — atomically, so it can never double-credit.
            supabase.table("agent_withdrawals").update({
                "failure_reason": transfer_msg or "Paystack transfer could not be initiated",
            }).eq("id", withdrawal_id).execute()

            logger.error(
                "PAYSTACK WITHDRAW: transfer could not be initiated for withdrawal %s "
                "(agent %s, GH₵%s) — Paystack said: %s. Leaving as 'processing'; "
                "background retry job will keep trying and auto-refund if needed.",
                withdrawal_id, agent_id, payout_amount, transfer_msg
            )
            return {
                "status":          "success",
                "provider":        "paystack",
                "message":         "Your withdrawal is active and being processed. "
                                   "Please try again shortly if it doesn't reflect.",
                "withdrawal_id":   withdrawal_id,
                "transfer_status": "processing",
                "amount":          amount,
                "fee":             fee,
                "payout_amount":   payout_amount,
            }

        tdata           = transfer.get("data", {})
        transfer_status = tdata.get("status")   # expected "success" | "pending" with OTP disabled

        # Safety net: if OTP somehow gets re-enabled on the Paystack dashboard
        # and a transfer comes back requiring it, we can't ask the agent for
        # a code they'll never receive — fail safely and refund instead of
        # silently holding their balance forever.
        if transfer_status == "otp":
            refund()
            supabase.table("agent_withdrawals").update({"status": "failed"}).eq("id", withdrawal_id).execute()
            logger.error(
                "PAYSTACK WITHDRAW: transfer %s came back requiring OTP — is 'Enable OTP for "
                "transfers' still on in the Paystack dashboard? Refunding agent %s.",
                withdrawal_id, agent_id
            )
            return {
                "error": "Withdrawals are temporarily unavailable. Please contact support.",
            }

        final_status = "paid" if transfer_status == "success" else "processing"

        supabase.table("agent_withdrawals").update({
            "status": final_status,
            "paystack_transfer_code": tdata.get("transfer_code"),
        }).eq("id", withdrawal_id).execute()

        supabase.table("agent_transactions").insert({
            "agent_id":  agent_id,
            "amount":    -amount,
            "type":      "withdrawal",
            "reference": paystack_ref,
        }).execute()

        return {
            "status":          "success",
            "provider":        "paystack",
            "message":         "Transfer initiated. Funds will arrive shortly.",
            "withdrawal_id":   withdrawal_id,
            "transfer_status": final_status,
            "amount":          amount,
            "fee":             fee,
            "payout_amount":   payout_amount,
        }

    # ── MOOLRE PATH (unchanged behaviour, now explicitly chosen) ──
    channel = MOOLRE_CHANNEL_MAP.get(network)
    if not channel:
        refund()
        return {"error": f"Unsupported network: {network}"}

    external_ref = f"EVOS-WD-{agent_id}-{uuid.uuid4().hex[:8].upper()}"

    wd = supabase.table("agent_withdrawals").insert({
        "agent_id":       agent_id,
        "amount":         amount,
        "fee":            fee,
        "payout_amount":  payout_amount,
        "account_name":   account_name,
        "account_number": mobile_number,
        "bank_name":      network,
        "status":         "processing",
        "provider":       "moolre",
        "moolre_ref":     external_ref,
    }).execute()

    if not wd.data:
        refund()
        return {"error": "Failed to create withdrawal record"}

    withdrawal_id = wd.data[0]["id"]

    try:
        # NOTE: only the post-fee amount is actually transferred. The agent's
        # wallet was already debited the full `amount` above.
        moolre_res = call_moolre("transfer", {
            "type":          1,
            "channel":       channel,
            "currency":      "GHS",
            "amount":        str(payout_amount),
            "receiver":      mobile_number,
            "externalref":   external_ref,
            "reference":     f"EVOS Agent Withdrawal #{withdrawal_id}",
            "accountnumber": MOOLRE_ACCOUNT_NUMBER,
        })

        if str(moolre_res.get("status")) == "1":
            tx_data      = moolre_res.get("data", {})
            tx_status    = tx_data.get("txstatus", 0) if isinstance(tx_data, dict) else 0
            final_status = "paid" if tx_status == 1 else "processing"
            supabase.table("agent_withdrawals").update({"status": final_status}).eq("id", withdrawal_id).execute()
            supabase.table("agent_transactions").insert({
                "agent_id":  agent_id,
                "amount":    -amount,
                "type":      "withdrawal",
                "reference": external_ref
            }).execute()
            return {
                "status":          "success",
                "provider":        "moolre",
                "message":         "Transfer initiated. Funds will arrive shortly.",
                "withdrawal_id":   withdrawal_id,
                "transfer_status": final_status,
                "amount":          amount,
                "fee":             fee,
                "payout_amount":   payout_amount,
            }
        else:
            refund()
            supabase.table("agent_withdrawals").update({"status": "failed"}).eq("id", withdrawal_id).execute()
            error_msg = moolre_res.get("message", "Transfer failed")
            if isinstance(error_msg, list):
                error_msg = " ".join(error_msg)
            return {"error": error_msg or "Moolre transfer failed"}

    except Exception as e:
        logger.error("MOOLRE TRANSFER ERROR: %s", str(e))
        refund()
        supabase.table("agent_withdrawals").update({"status": "failed"}).eq("id", withdrawal_id).execute()
        return {"error": "Transfer service error. Funds refunded to wallet."}

# =========================
# AGENT WITHDRAW — VERIFY ACCOUNT (resolves name before confirming)
# =========================
@router.post("/agent/withdraw/verify-account")
@limiter.limit("10/minute")
async def verify_withdraw_account(request: Request, payload: VerifyAccountRequest):
    token = request.headers.get("X-Agent-Token", "")
    if not token or not verify_agent_token(token, payload.agent_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    network = payload.network.upper()

    if payload.provider == "paystack":
        bank_code = PAYSTACK_MOMO_BANK_CODE.get(network)
        if not bank_code:
            return {"status": "error", "message": f"Unsupported network for Paystack: {network}"}

        # Resolve the real account name first — /transferrecipient alone
        # doesn't reliably return this for mobile money. NOTE: Paystack's
        # Resolve Account Number coverage for Ghana mobile money is uneven
        # per network — MTN tends to resolve reliably; Telecel/AirtelTigo
        # frequently come back status:false with no name on file. We keep
        # `resolve_message` so the frontend can show *why* it's unresolved
        # instead of just a blanket "Not verified".
        resolved = paystack_resolve_account(payload.mobile_number, bank_code)
        resolved_name = ""
        resolve_message = None
        if resolved.get("status"):
            resolved_name = resolved.get("data", {}).get("account_name", "") or ""
        else:
            resolve_message = resolved.get("message") or "Could not resolve account name for this number."
            logger.warning(
                "PAYSTACK RESOLVE: could not resolve %s on %s: %s",
                payload.mobile_number, network, resolve_message
            )

        recipient = paystack_create_recipient(resolved_name or "EVOS Agent", payload.mobile_number, network)
        if not recipient.get("status"):
            error_msg = recipient.get("message", "Could not verify account")
            return {"status": "error", "message": error_msg}

        rdata = recipient.get("data", {})
        details = rdata.get("details", {})
        # Prefer the name from the dedicated resolve call; fall back to
        # whatever (if anything) the recipient creation echoed back.
        account_name = resolved_name or details.get("account_name") or ""

        return {
            "status": "success",
            "provider": "paystack",
            "account_name": account_name,
            "recipient_code": rdata.get("recipient_code"),
            "mobile_number": payload.mobile_number,
            "network": network,
            "resolved": bool(account_name),
            "resolve_message": None if account_name else resolve_message,
        }

    # Moolre has no name-resolution endpoint in this integration —
    # fall back to whatever name the agent types in on the frontend.
    return {
        "status": "success",
        "provider": "moolre",
        "account_name": "",
        "mobile_number": payload.mobile_number,
        "network": network,
        "resolved": False,
        "resolve_message": None,
        "note": "Moolre does not support account name lookup — agent must confirm name manually.",
    }
        

@router.get("/agent/withdrawal/status/{withdrawal_id}")
@limiter.limit("20/minute")
async def check_withdrawal_status(request: Request, withdrawal_id: int):
    try:
        wd = supabase.table("agent_withdrawals").select("*").eq("id", withdrawal_id).limit(1).execute()
        if not wd.data:
            return {"error": "Withdrawal not found"}

        row = wd.data[0]

        token = request.headers.get("X-Agent-Token", "")
        if not token or not verify_agent_token(token, row["agent_id"]):
            raise HTTPException(status_code=403, detail="Forbidden")

        if row.get("status") in ["paid", "failed", "rejected"]:
            return {"status": row.get("status"), "withdrawal": row}

        provider = row.get("provider", "moolre")
        final_status = row.get("status")

        if provider == "paystack":
            ref = row.get("paystack_ref")
            if not ref:
                return {"status": final_status, "withdrawal": row}
            # Nothing was ever sent to Paystack for this reference (initiate
            # failed synchronously, e.g. low business balance) — there's
            # nothing to verify yet. Leave it to the background retry job.
            if not row.get("paystack_transfer_code"):
                return {"status": final_status, "withdrawal": row}
            result = paystack_verify_transfer(ref)
            if result.get("status"):
                t_status = result.get("data", {}).get("status")
                final_status = "paid" if t_status == "success" else "failed" if t_status == "failed" else "processing"
        else:
            moolre_ref = row.get("moolre_ref")
            if not moolre_ref:
                return {"status": final_status, "withdrawal": row}
            status_res = call_moolre("status", {
                "type":          1,
                "idtype":        1,
                "id":            moolre_ref,
                "accountnumber": MOOLRE_ACCOUNT_NUMBER,
            })
            if str(status_res.get("status")) == "1":
                tx_status    = status_res.get("data", {}).get("txstatus", 0)
                final_status = "paid" if tx_status == 1 else "failed" if tx_status == 2 else "processing"

        if final_status in ("paid", "failed") and final_status != row.get("status"):
            if provider == "paystack":
                # Atomic — safe even if the webhook or the retry job is
                # resolving this exact withdrawal at the same moment.
                finalize_paystack_withdrawal(row, final_status, note="Resolved via agent status poll")
            else:
                supabase.table("agent_withdrawals").update({"status": final_status}).eq("id", withdrawal_id).execute()
                if final_status == "failed":
                    wlt = supabase.table("agent_wallets").select("balance").eq("agent_id", row["agent_id"]).limit(1).execute()
                    if wlt.data:
                        supabase.table("agent_wallets").update({
                            "balance": round(float(wlt.data[0]["balance"]) + float(row["amount"]), 2)
                        }).eq("agent_id", row["agent_id"]).execute()

        return {"status": final_status, "withdrawal": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("WITHDRAWAL STATUS ERROR: %s", str(e))
        return {"error": "Failed to check status"}

# =========================
# MOOLRE WEBHOOK
# =========================
@router.post("/webhook/moolre")
async def moolre_webhook(request: Request):
    try:
        payload      = await request.json()
        data         = payload.get("data", {})
        external_ref = data.get("externalref") or payload.get("externalref")
        tx_status    = data.get("txstatus") if isinstance(data, dict) else payload.get("txstatus")

        if not external_ref:
            return {"received": True}

        if not str(external_ref).startswith("EVOS-WD-"):
            logger.info("MOOLRE WEBHOOK: ignoring non-withdrawal ref %s", external_ref)
            return {"received": True}

        wd = supabase.table("agent_withdrawals").select("*").eq("moolre_ref", external_ref).limit(1).execute()
        if not wd.data:
            logger.warning("MOOLRE WEBHOOK: withdrawal not found for ref %s", external_ref)
            return {"received": True}

        row = wd.data[0]
        final_status = (
            "paid"        if tx_status == 1
            else "failed" if tx_status == 2
            else "processing"
        )

        supabase.table("agent_withdrawals").update({"status": final_status}).eq("moolre_ref", external_ref).execute()

        if final_status == "paid" and row.get("status") != "paid":
            supabase.table("agent_transactions").insert({
                "agent_id":  row["agent_id"],
                "amount":    -float(row["amount"]),
                "type":      "withdrawal",
                "reference": external_ref
            }).execute()

        if final_status == "failed" and row.get("status") != "failed":
            wlt = supabase.table("agent_wallets").select("balance").eq("agent_id", row["agent_id"]).limit(1).execute()
            if wlt.data:
                current = float(wlt.data[0]["balance"])
                supabase.table("agent_wallets").update({
                    "balance": current + float(row["amount"])
                }).eq("agent_id", row["agent_id"]).execute()
                logger.info("MOOLRE WEBHOOK: refunded GH₵%s to agent %s", row['amount'], row['agent_id'])

        logger.info("MOOLRE WEBHOOK: withdrawal %s updated to %s", external_ref, final_status)
        return {"received": True}
    except Exception as e:
        logger.error("MOOLRE WEBHOOK ERROR: %s", str(e))
        return {"received": False}


# =========================
# AGENT PRICING
# =========================
@router.get("/agent/pricing/{agent_id}")
@limiter.limit("30/minute")
def get_agent_pricing(request: Request, agent_id: int, _: int = Depends(require_agent)):
    try:
        base_res     = supabase.table("base_prices").select("*").execute()
        base_prices  = base_res.data or []

        override_res = supabase.table("admin_agent_prices") \
            .select("*") \
            .eq("agent_id", agent_id) \
            .execute()
        override_prices = override_res.data or []

        override_map = {}
        for row in override_prices:
            if not row:
                continue
            key = f"{row.get('network','').strip().lower()}-{row.get('bundle','').strip().lower()}"
            override_map[key] = float(row.get("cost_price", 0) or 0)

        agent_res    = supabase.table("agent_prices").select("*").eq("agent_id", agent_id).execute()
        agent_prices = agent_res.data or []

        markup_map = {}
        for row in agent_prices:
            if not row:
                continue
            key = f"{row.get('network','').strip().lower()}-{row.get('bundle','').strip().lower()}"
            markup_map[key] = float(row.get("markup", 0) or 0)

        result = []
        for item in base_prices:
            if not item:
                continue
            network  = item.get("network", "").strip()
            bundle   = item.get("bundle", "").strip()
            key      = f"{network.lower()}-{bundle.lower()}"

            if key in override_map:
                base_price = override_map[key]
            else:
                base_price = float(item.get("cost_price", 0) or 0)

            markup = float(markup_map.get(key, 0) or 0)
            result.append({
                "network":          network,
                "bundle":           bundle,
                "base_price":       base_price,
                "markup":           markup,
                "final_price":      round(base_price + markup, 2),
                "has_override":     key in override_map,
            })

        try:
            datamart_stock.annotate(result)
        except Exception as stock_err:
            logger.warning("AGENT PRICING: stock annotate skipped (%s)", stock_err)

        return {"status": "success", "prices": result}
    except Exception as e:
        logger.error("AGENT PRICING ERROR: %s", str(e))
        return {"status": "error", "prices": []}


@router.post("/agent/pricing/save")
@limiter.limit("10/minute")
def save_agent_pricing(request: Request, payload: dict):
    try:
        agent_id = str(payload.get("agent_id", "")).strip()
        prices   = payload.get("prices", [])

        if not agent_id:
            return {"status": "failed", "message": "agent_id required"}

        token = request.headers.get("X-Agent-Token", "")
        try:
            agent_id_int = int(agent_id)
        except ValueError:
            return {"status": "failed", "message": "Invalid agent_id"}
        if not token or not verify_agent_token(token, agent_id_int):
            raise HTTPException(status_code=403, detail="Forbidden")

        supabase.table("agent_prices").delete().eq("agent_id", agent_id).execute()

        rows = []
        for item in prices:
            network = str(item.get("network", "")).strip()
            bundle  = str(item.get("bundle", "")).strip()
            try:
                markup = float(item.get("markup", 0) or 0)
            except:
                markup = 0
            rows.append({"agent_id": agent_id, "network": network, "bundle": bundle, "markup": markup})

        if rows:
            supabase.table("agent_prices").insert(rows).execute()

        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("SAVE AGENT PRICING ERROR: %s", str(e))
        return {"status": "failed", "message": "Unable to save pricing"}


# =========================
# AGENT CHECKER PRICING
# Lets an agent set their own resale price per checker type (WAEC/BECE).
# Stored as a markup on top of CHECKER_AGENT_BASE_PRICE, same shape as the
# data-bundle agent_prices table above — final_price = base + markup.
# Markup must be >= 0: agents can only increase their price, never sell
# below their own cost.
# =========================
CHECKER_TYPES = ("WAEC", "BECE")


@router.get("/agent/checker-pricing/{agent_id}")
@limiter.limit("30/minute")
def get_agent_checker_pricing(request: Request, agent_id: int, _: int = Depends(require_agent)):
    try:
        rows_res = supabase.table("checker_agent_prices") \
            .select("*") \
            .eq("agent_id", agent_id) \
            .execute()
        rows = rows_res.data or []

        markup_map = {}
        for row in rows:
            if not row:
                continue
            markup_map[row.get("checker_type", "").strip().upper()] = float(row.get("markup", 0) or 0)

        result = []
        for checker_type in CHECKER_TYPES:
            markup = float(markup_map.get(checker_type, 0) or 0)
            result.append({
                "checker_type": checker_type,
                "base_price":   CHECKER_AGENT_BASE_PRICE,
                "markup":       markup,
                "final_price":  round(CHECKER_AGENT_BASE_PRICE + markup, 2),
            })

        return {"status": "success", "prices": result}
    except Exception as e:
        logger.error("AGENT CHECKER PRICING ERROR: %s", str(e))
        return {"status": "error", "prices": []}


@router.post("/agent/checker-pricing/save")
@limiter.limit("10/minute")
def save_agent_checker_pricing(request: Request, payload: dict):
    try:
        agent_id = str(payload.get("agent_id", "")).strip()
        prices   = payload.get("prices", [])

        if not agent_id:
            return {"status": "failed", "message": "agent_id required"}

        token = request.headers.get("X-Agent-Token", "")
        try:
            agent_id_int = int(agent_id)
        except ValueError:
            return {"status": "failed", "message": "Invalid agent_id"}
        if not token or not verify_agent_token(token, agent_id_int):
            raise HTTPException(status_code=403, detail="Forbidden")

        rows = []
        for item in prices:
            checker_type = str(item.get("checker_type", "")).strip().upper()
            if checker_type not in CHECKER_TYPES:
                continue
            try:
                markup = float(item.get("markup", 0) or 0)
            except:
                markup = 0
            # Agents can only mark UP from their base cost, never below it.
            if markup < 0:
                return {
                    "status": "failed",
                    "message": f"{checker_type} price can't be below the base price of GH₵ {CHECKER_AGENT_BASE_PRICE:.2f}",
                }
            rows.append({"agent_id": agent_id, "checker_type": checker_type, "markup": markup})

        supabase.table("checker_agent_prices").delete().eq("agent_id", agent_id).execute()
        if rows:
            supabase.table("checker_agent_prices").insert(rows).execute()

        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("SAVE AGENT CHECKER PRICING ERROR: %s", str(e))
        return {"status": "failed", "message": "Unable to save pricing"}


# =========================
# ADMIN: PER-AGENT BASE PRICE OVERRIDES
# =========================
@router.get("/admin/agent-prices")
def admin_get_agent_prices(request: Request, _: None = Depends(require_admin)):
    try:
        rows = supabase.table("admin_agent_prices").select("*").order("agent_id").execute()
        return {"status": "success", "data": rows.data or []}
    except Exception as e:
        logger.error("ADMIN AGENT PRICES GET ERROR: %s", str(e))
        raise HTTPException(500, "Failed to fetch agent prices")


@router.post("/admin/agent-prices")
def admin_set_agent_price(request: Request, payload: dict, _: None = Depends(require_admin)):
    try:
        agent_id   = int(payload["agent_id"])
        network    = str(payload["network"]).strip().upper()
        bundle     = str(payload["bundle"]).strip()
        cost_price = float(payload["cost_price"])

        supabase.table("admin_agent_prices").upsert({
            "agent_id":   agent_id,
            "network":    network,
            "bundle":     bundle,
            "cost_price": cost_price,
            "updated_at": utc_now().isoformat(),
        }, on_conflict="agent_id,network,bundle").execute()

        return {"status": "success"}
    except Exception as e:
        logger.error("ADMIN AGENT PRICES SET ERROR: %s", str(e))
        raise HTTPException(500, "Failed to set agent price")


@router.delete("/admin/agent-prices/{override_id}")
def admin_delete_agent_price(override_id: int, request: Request, _: None = Depends(require_admin)):
    try:
        supabase.table("admin_agent_prices").delete().eq("id", override_id).execute()
        return {"status": "deleted"}
    except Exception as e:
        logger.error("ADMIN AGENT PRICES DELETE ERROR: %s", str(e))
        raise HTTPException(500, "Failed to delete")

# =========================
# AGENT WALLET DEPOSIT
# =========================
@router.post("/agent/deposit/initiate")
@limiter.limit("10/minute")
async def initiate_deposit(request: Request, payload: DepositInitiateRequest):
    try:
        token = request.headers.get("X-Agent-Token", "")
        if not token or not verify_agent_token(token, payload.agent_id):
            raise HTTPException(status_code=403, detail="Forbidden")

        agent_id     = payload.agent_id
        amount       = payload.amount
        total_charge = payload.total_charge

        user_res = supabase.table("users").select("email, username").eq("id", agent_id).limit(1).execute()
        if not user_res.data:
            return {"error": "Agent not found"}

        agent_email = user_res.data[0].get("email", "")
        reference   = f"EVOS-DEP-{agent_id}-{uuid.uuid4().hex[:10].upper()}"

        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://api.paystack.co/transaction/initialize",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
                json={
                    "email":     agent_email,
                    "amount":    int(total_charge * 100),
                    "reference": reference,
                    "currency":  "GHS",
                    "metadata": {
                        "agent_id":      agent_id,
                        "type":          "wallet_deposit",
                        "credit_amount": amount,
                    },
                    "callback_url": f"{callback_base(request)}/success?type=deposit",
                },
            )
            data = res.json()

        if not data.get("status"):
            return {"error": data.get("message", "Paystack init failed")}

        paystack_ref = data["data"].get("reference", reference)

        supabase.table("wallet_deposits").insert({
            "agent_id":     agent_id,
            "reference":    reference,
            "paystack_ref": paystack_ref,
            "amount":       amount,
            "total_charge": total_charge,
            "status":       "pending",
        }).execute()

        return {"status": "created", "reference": reference, "payment_url": data["data"]["authorization_url"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("DEPOSIT INITIATE ERROR: %s", str(e))
        return {"error": "Failed to initiate deposit"}


@router.post("/agent/deposit/verify")
@limiter.limit("20/minute")
async def verify_deposit(request: Request, payload: dict):
    try:
        reference = str(payload.get("reference", "")).strip()
        if not reference:
            return {"error": "reference required"}

        lookup_col = "reference" if reference.startswith("EVOS-DEP-") else "paystack_ref"

        existing = supabase.table("wallet_deposits").select("*").eq(lookup_col, reference).limit(1).execute()
        if not existing.data:
            return {"error": "Deposit record not found"}

        deposit = existing.data[0]

        token = request.headers.get("X-Agent-Token", "")
        if not token or not verify_agent_token(token, deposit["agent_id"]):
            raise HTTPException(status_code=403, detail="Forbidden")

        if deposit.get("status") == "credited":
            wallet_res = supabase.table("agent_wallets").select("balance").eq("agent_id", deposit["agent_id"]).limit(1).execute()
            balance = float(wallet_res.data[0]["balance"]) if wallet_res.data else 0
            return {"status": "already_credited", "wallet_balance": balance}

        verify_ref = deposit.get("paystack_ref") or deposit.get("reference")
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"https://api.paystack.co/transaction/verify/{verify_ref}",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"},
            )
            data = res.json()

        if not data.get("status") or data["data"].get("status") != "success":
            supabase.table("wallet_deposits").update({"status": "failed"}).eq("id", deposit["id"]).execute()
            return {"error": "Payment not successful", "paystack_status": data["data"].get("status")}

        agent_id      = deposit["agent_id"]
        credit_amount = float(deposit["amount"])

        # ── ATOMIC CLAIM ──────────────────────────────────────────────
        # Flip status pending -> credited FIRST, gated on it not already
        # being "credited". Only the caller whose update actually affects a
        # row (i.e. wins the race) proceeds to touch the wallet. This closes
        # the gap that let this endpoint and retry_stuck_deposits() (or two
        # concurrent calls to this same endpoint) both credit the same
        # deposit — which is exactly what caused the double GH₵1.00 credit.
        claim = supabase.table("wallet_deposits") \
            .update({"status": "credited"}) \
            .eq("id", deposit["id"]) \
            .neq("status", "credited") \
            .execute()

        if not claim.data:
            wallet_res = supabase.table("agent_wallets").select("balance").eq("agent_id", agent_id).limit(1).execute()
            balance = float(wallet_res.data[0]["balance"]) if wallet_res.data else 0
            return {"status": "already_credited", "wallet_balance": balance}

        # Belt-and-suspenders: also guard on the transaction reference
        # itself, matching the pattern used for order/checker profit crediting.
        existing_tx = supabase.table("agent_transactions").select("id").eq("reference", deposit.get("reference")).limit(1).execute()
        if existing_tx.data:
            wallet_res = supabase.table("agent_wallets").select("balance").eq("agent_id", agent_id).limit(1).execute()
            balance = float(wallet_res.data[0]["balance"]) if wallet_res.data else 0
            return {"status": "already_credited", "wallet_balance": balance}

        wallet_res = supabase.table("agent_wallets").select("balance").eq("agent_id", agent_id).limit(1).execute()
        if wallet_res.data:
            current_balance = float(wallet_res.data[0]["balance"] or 0)
            new_balance     = round(current_balance + credit_amount, 2)
            supabase.table("agent_wallets").update({"balance": new_balance}).eq("agent_id", agent_id).execute()
        else:
            new_balance = round(credit_amount, 2)
            supabase.table("agent_wallets").insert({"agent_id": agent_id, "balance": new_balance}).execute()

        supabase.table("agent_transactions").insert({
            "agent_id":  agent_id,
            "type":      "credit",
            "amount":    credit_amount,
            "reference": deposit.get("reference"),
            "note":      "Wallet top-up via Paystack",
        }).execute()

        return {"status": "credited", "credited_amount": credit_amount, "wallet_balance": new_balance}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("DEPOSIT VERIFY ERROR: %s", str(e))
        return {"error": "Verification failed"}


# =========================
# AGENT BUY DATA
# =========================
@router.post("/agent/buy-data")
@limiter.limit("10/minute")
async def agent_buy_data(request: Request, payload: AgentBuyDataRequest):
    try:
        token = request.headers.get("X-Agent-Token", "")
        if not token or not verify_agent_token(token, payload.agent_id):
            raise HTTPException(status_code=403, detail="Forbidden")

        agent_id     = payload.agent_id
        network      = payload.network
        bundle       = payload.bundle
        phone_number = payload.phone_number

        if not datamart_stock.bundle_in_stock(network, bundle):
            return {"status": "error", "message": datamart_stock.OUT_OF_STOCK_MESSAGE}

        override_res = supabase.table("admin_agent_prices") \
            .select("cost_price") \
            .eq("agent_id", agent_id) \
            .ilike("network", network) \
            .ilike("bundle", bundle) \
            .limit(1) \
            .execute()

        if override_res.data:
            cost_price = float(override_res.data[0]["cost_price"])
        else:
            price_res = supabase.table("base_prices") \
                .select("cost_price") \
                .ilike("network", network) \
                .ilike("bundle", bundle) \
                .limit(1) \
                .execute()
            if not price_res.data:
                return {"status": "error", "message": "Bundle not found"}
            cost_price = float(price_res.data[0].get("cost_price", 0))

        if cost_price <= 0:
            return {"status": "error", "message": "Invalid bundle price"}

        agent_res = supabase.table("users") \
            .select("username") \
            .eq("id", agent_id) \
            .eq("role", "agent") \
            .eq("agent_status", "approved") \
            .limit(1) \
            .execute()
        if not agent_res.data:
            return {"status": "error", "message": "Agent not found or not approved"}

        # ── DUPLICATE GUARD ─────────────────────────────────────────────
        # Block the exact same agent+network+bundle+phone combo from being
        # bought again within 5 minutes (accidental double-click / double-tap,
        # or a resubmit after a slow response). Looks at recent orders
        # regardless of status, since even a "failed" one still means the
        # same request just went through moments ago.
        dupe_floor = (utc_now() - timedelta(minutes=5)).isoformat()
        dupe_res = supabase.table("orders") \
            .select("id, created_at") \
            .eq("agent_id", agent_id) \
            .ilike("network", network) \
            .ilike("bundle", bundle) \
            .eq("phone_number", phone_number) \
            .gte("created_at", dupe_floor) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if dupe_res.data:
            last_order_at = parse_db_dt(dupe_res.data[0]["created_at"])
            wait_left = timedelta(minutes=5) - (utc_now() - last_order_at)
            wait_seconds = max(int(wait_left.total_seconds()), 1)
            return {
                "status": "error",
                "message": (
                    f"You just bought {bundle} for {phone_number} moments ago. "
                    f"Please wait {wait_seconds}s before repeating this exact order."
                ),
                "duplicate": True,
                "retry_after_seconds": wait_seconds,
            }

        wallet_res = supabase.table("agent_wallets").select("balance").eq("agent_id", agent_id).limit(1).execute()
        wallet_balance = float(wallet_res.data[0]["balance"]) if wallet_res.data else 0.0

        if wallet_balance < cost_price:
            return {"status": "error", "message": f"Insufficient wallet balance. Need GH₵ {cost_price:.2f}, have GH₵ {wallet_balance:.2f}"}

        new_balance = round(wallet_balance - cost_price, 2)
        supabase.table("agent_wallets").update({"balance": new_balance}).eq("agent_id", agent_id).execute()

        reference = f"EVOS-AGT-{agent_id}-{uuid.uuid4().hex[:10].upper()}"

        order_res = supabase.table("orders").insert({
            "agent_id":     agent_id,
            "network":      network,
            "bundle":       bundle,
            "phone_number": phone_number,
            "price":        cost_price,
            "evosdata_ref": reference,
            "paystack_ref": reference,
            "status":       "processing",
        }).execute()

        if not order_res.data:
            supabase.table("agent_wallets").update({"balance": wallet_balance}).eq("agent_id", agent_id).execute()
            return {"status": "error", "message": "Failed to create order"}

        order_id = order_res.data[0].get("id")

        supabase.table("agent_transactions").insert({
            "agent_id":  agent_id,
            "type":      "debit",
            "amount":    cost_price,
            "reference": reference,
            "order_id":  order_id,
        }).execute()

        try:
            provider = get_provider(network)

            if provider == "DATAMART":
                dm_response = datamart_stock.purchase_post(
                    f"{DATAMART_BASE}/purchase",
                    headers={"X-API-Key": DATAMART_API_KEY},
                    json={
                        "phoneNumber": phone_number,
                        "network":     NETWORK_MAP.get(network.upper()),
                        "capacity":    extract_capacity(bundle),
                        "gateway":     "wallet"
                    },
                    timeout=REQUEST_TIMEOUT
                )
                dm = dm_response.json()
                dm_data = dm.get("data", {})
                supabase.table("orders").update({
                    "datamart_ref": dm_data.get("orderReference"),
                    "datamart_order_id": dm_data.get("orderId"),
                    "status": "processing"
                }).eq("id", order_id).execute()

            elif provider == "BUNDLES_GHANA":
                BG_NETWORK_MAP = {"MTN": "MTN", "TELECEL": "Telecel", "AIRTELTIGO": "AirtelTigo"}
                network_name = BG_NETWORK_MAP.get(network.upper(), network)
                bg_bundles = call_bundles_ghana(f"/bundles?network={network_name}")
                if bg_bundles.get("success"):
                    bundle_volume = bundle.upper().replace(" ", "")
                    matched = next(
                        (b for b in bg_bundles.get("bundles", [])
                         if b.get("volume", "").upper().replace(" ", "") == bundle_volume
                         and b.get("status") == "active"),
                        None
                    )
                    if matched:
                        bg_order = call_bundles_ghana("/order", method="POST", body={
                            "bundle_id":   matched["id"],
                            "phone":       phone_number,
                            "webhook_url": "https://api.evosdata.xyz/webhook/bundlesghana"
                        })
                        if bg_order.get("success"):
                            supabase.table("orders").update({
                                "datamart_ref": bg_order["order"]["reference"],
                                "datamart_order_id": str(bg_order["order"]["id"]),
                                "status": "processing"
                            }).eq("id", order_id).execute()

            elif provider == "SWIFT_DATA_LINK":
                volume = float(extract_capacity(bundle) or 0)
                sdl = call_swift_data_link(network=network, volume=volume, phone=phone_number)
                if sdl.get("success"):
                    supabase.table("orders").update({
                        "datamart_ref": sdl.get("reference"),
                        "datamart_order_id": sdl.get("orderId"),
                        "status": "processing"
                    }).eq("id", order_id).execute()

            elif provider == "AGYEKUMDATA":
                package_id = get_agyekumdata_package_id(network, bundle)
                safe_ref   = sanitise_agyekumdata_ref(reference)
                agd        = call_agyekumdata_purchase(
                    package_id=package_id,
                    phone=phone_number,
                    client_reference=reference,
                )
                if agd.get("success"):
                    agd_data = agd.get("data", {})
                    supabase.table("orders").update({
                        "datamart_ref":      agd_data.get("clientReference") or safe_ref,
                        "datamart_order_id": agd_data.get("orderId"),
                        "status":            "processing",
                    }).eq("id", order_id).execute()
                    logger.info(
                        "AGENT BUY DATA: order %s dispatched to AGYEKUMDATA orderId=%s ✅",
                        order_id, agd_data.get("orderId")
                    )
                else:
                    logger.warning(
                        "AGENT BUY DATA: AGYEKUMDATA rejected order %s: %s",
                        order_id, agd
                    )

        except Exception as dispatch_err:
            logger.error("AGENT BUY DATA DISPATCH ERROR: %s", str(dispatch_err))

        return {
            "status":             "success",
            "message":            f"{bundle} queued for {phone_number}",
            "reference":          reference,
            "order_id":           order_id,
            "new_wallet_balance": new_balance,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AGENT BUY DATA ERROR: %s", str(e))
        return {"status": "error", "message": "Something went wrong. Please try again."}


# =========================
# AGENT STORE
# =========================
@router.get("/store/{agent_id}")
@limiter.limit("60/minute")
async def public_agent_store(request: Request, agent_id: int):
    try:
        user = supabase.table("users") \
            .select("id,username,full_name,store_name,store_logo,role,agent_status") \
            .eq("id", agent_id).limit(1).execute()
        if not user.data:
            return {"status": "error", "message": "Store not found"}
        u = user.data[0]
        if u.get("role") != "agent" or u.get("agent_status") != "approved":
            return {"status": "error", "message": "Store unavailable"}

        prices  = supabase.table("base_prices").select("*").order("network").execute()
        markups = supabase.table("agent_prices").select("*").eq("agent_id", agent_id).execute()

        markup_map = {}
        for m in (markups.data or []):
            key = f"{m['network'].strip().lower()}::{m['bundle'].strip().lower()}"
            markup_map[key] = float(m.get("markup", 0) or 0)

        bundles = []
        for row in (prices.data or []):
            network    = row.get("network", "").strip()
            bundle     = row.get("bundle", "").strip()
            key        = f"{network.lower()}::{bundle.lower()}"
            base_price = float(row.get("cost_price", 0) or 0)
            markup     = float(markup_map.get(key, 0))
            bundles.append({
                "network":     network,
                "bundle":      bundle,
                "base_price":  base_price,
                "markup":      markup,
                "final_price": round(base_price + markup, 2)
            })

        try:
            datamart_stock.annotate(bundles)
        except Exception as stock_err:
            logger.warning("STORE: stock annotate skipped (%s)", stock_err)

        checker_markups = supabase.table("checker_agent_prices").select("*").eq("agent_id", agent_id).execute()
        checker_markup_map = {}
        for m in (checker_markups.data or []):
            checker_markup_map[str(m.get("checker_type", "")).strip().upper()] = float(m.get("markup", 0) or 0)

        checkers = []
        for checker_type in CHECKER_TYPES:
            markup = float(checker_markup_map.get(checker_type, 0) or 0)
            checkers.append({
                "checker_type": checker_type,
                "base_price":   CHECKER_AGENT_BASE_PRICE,
                "markup":       markup,
                "final_price":  round(CHECKER_AGENT_BASE_PRICE + markup, 2),
            })

        return {
            "status":     "success",
            "agent_id":   agent_id,
            "agent_name": u.get("store_name") or u.get("username") or u.get("full_name") or "Agent",
            # Base64 data URI of the agent's uploaded logo, or None if they
            # never set one — frontend falls back to the default EVOS logo.
            "logo":       u.get("store_logo") or None,
            "prices":     bundles,
            "checkers":   checkers
        }
    except Exception as e:
        logger.error("STORE ERROR: %s", str(e))
        return {"status": "error", "message": "Failed to load store"}


@router.post("/agent/store-name")
@limiter.limit("10/minute")
async def save_store_name(request: Request, payload: dict):
    try:
        agent_id   = payload.get("agent_id")
        store_name = str(payload.get("store_name", "")).strip()
        if not agent_id:
            return {"error": "agent_id required"}

        token = request.headers.get("X-Agent-Token", "")
        try:
            agent_id_int = int(agent_id)
        except (ValueError, TypeError):
            return {"error": "Invalid agent_id"}
        if not token or not verify_agent_token(token, agent_id_int):
            raise HTTPException(status_code=403, detail="Forbidden")

        if len(store_name) > 40:
            return {"error": "Store name must be 40 characters or less"}
        supabase.table("users").update({"store_name": store_name or None}).eq("id", agent_id).execute()
        return {"status": "success", "store_name": store_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("SAVE STORE NAME ERROR: %s", str(e))
        return {"error": "Failed to save store name"}


@router.get("/agent/store-name/{agent_id}")
@limiter.limit("30/minute")
async def get_store_name(request: Request, agent_id: int, _: int = Depends(require_agent)):
    try:
        res = supabase.table("users").select("store_name, username").eq("id", agent_id).limit(1).execute()
        if not res.data:
            return {"error": "Agent not found"}
        return {"store_name": res.data[0].get("store_name") or "", "username": res.data[0].get("username") or ""}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("GET STORE NAME ERROR: %s", str(e))
        return {"error": "Failed to fetch store name"}


# =========================
# AGENT STORE LOGO
# Stored directly as a base64 data URI in users.store_logo — no separate
# object storage/bucket needed. The frontend compresses/resizes to a small
# square (see AgentDashboard.jsx) before upload, and STORE_LOGO_MAX_BYTES
# below is a hard server-side backstop against an oversized payload landing
# in the DB regardless of what the client claims to have done.
# Empty string clears the logo, so the store page falls back to the
# default EVOS logo — same pattern as clearing store_name.
#
#      Requires this column on the "users" table (run once in Supabase):
#        alter table users add column if not exists store_logo text;
# =========================
STORE_LOGO_MAX_BYTES = 200_000  # ~200KB decoded; keeps the users table lean

@router.post("/agent/store-logo")
@limiter.limit("10/minute")
async def save_store_logo(request: Request, payload: dict):
    try:
        agent_id    = payload.get("agent_id")
        logo_base64 = str(payload.get("logo_base64", "")).strip()

        if not agent_id:
            return {"error": "agent_id required"}

        token = request.headers.get("X-Agent-Token", "")
        try:
            agent_id_int = int(agent_id)
        except (ValueError, TypeError):
            return {"error": "Invalid agent_id"}
        if not token or not verify_agent_token(token, agent_id_int):
            raise HTTPException(status_code=403, detail="Forbidden")

        # Empty payload = agent removing their custom logo, reverting to default.
        if not logo_base64:
            supabase.table("users").update({"store_logo": None}).eq("id", agent_id).execute()
            return {"status": "success", "logo": None}

        if not logo_base64.startswith("data:image/"):
            return {"error": "Logo must be an image file"}

        # Rough decoded-size check on the base64 payload itself, cheap and
        # good enough as a backstop (base64 inflates size by ~4/3).
        approx_decoded_bytes = int(len(logo_base64) * 3 / 4)
        if approx_decoded_bytes > STORE_LOGO_MAX_BYTES:
            return {"error": "Logo image is too large. Please use a smaller image."}

        supabase.table("users").update({"store_logo": logo_base64}).eq("id", agent_id).execute()
        return {"status": "success", "logo": logo_base64}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("SAVE STORE LOGO ERROR: %s", str(e))
        return {"error": "Failed to save store logo"}


@router.get("/agent/store-logo/{agent_id}")
@limiter.limit("30/minute")
async def get_store_logo(request: Request, agent_id: int, _: int = Depends(require_agent)):
    try:
        res = supabase.table("users").select("store_logo").eq("id", agent_id).limit(1).execute()
        if not res.data:
            return {"error": "Agent not found"}
        return {"logo": res.data[0].get("store_logo") or None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("GET STORE LOGO ERROR: %s", str(e))
        return {"error": "Failed to fetch store logo"}


# =========================
# STORE ORDER
# =========================
@router.post("/store/order")
@limiter.limit("10/minute")
async def create_store_order(request: Request, payload: StoreOrderRequest):
    try:
        agent_id       = payload.agent_id
        network        = payload.network
        bundle         = payload.bundle
        phone_number   = payload.phone_number
        customer_email = str(payload.email or "customer@evoshub.store").strip()

        if not datamart_stock.bundle_in_stock(network, bundle):
            return {"status": "error", "message": datamart_stock.OUT_OF_STOCK_MESSAGE}

        agent = supabase.table("users") \
            .select("id,role,agent_status,full_name,username") \
            .eq("id", agent_id).limit(1).execute()
        if not agent.data:
            return {"status": "error", "message": "Store not found"}
        user = agent.data[0]
        if user.get("role") != "agent" or user.get("agent_status") != "approved":
            return {"status": "error", "message": "Store unavailable"}

        base = supabase.table("base_prices").select("cost_price").eq("network", network).eq("bundle", bundle).limit(1).execute()
        if not base.data:
            return {"status": "error", "message": "Bundle not found"}
        base_price = float(base.data[0]["cost_price"])

        markup = supabase.table("agent_prices").select("markup") \
            .eq("agent_id", agent_id).eq("network", network).eq("bundle", bundle).limit(1).execute()
        markup_price = float(markup.data[0].get("markup", 0) or 0) if markup.data else 0.0
        agent_price  = round(base_price + markup_price, 2)

        reference = f"STORE-{agent_id}-{uuid.uuid4().hex[:10].upper()}"

        order = supabase.table("orders").insert({
            "agent_id":     agent_id,
            "email":        customer_email,
            "network":      network,
            "bundle":       bundle,
            "price":        agent_price,
            "phone_number": phone_number,
            "paystack_ref": reference,
            "status":       "pending_payment",
            "base_price":   base_price,
            "agent_price":  agent_price,
            "profit":       markup_price
        }).execute()

        if not order.data:
            return {"status": "error", "message": "Failed to create order"}

        order_id = order.data[0]["id"]

        pay = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json={
                "email":        customer_email,
                "amount":       int(agent_price * 100),
                "reference":    reference,
                "callback_url": f"{callback_base(request)}/store/{agent_id}",
                "metadata":     {"order_id": order_id, "agent_id": agent_id, "network": network, "bundle": bundle}
            },
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
            timeout=30
        )
        pay_data = pay.json()

        if not pay_data.get("status"):
            supabase.table("orders").delete().eq("id", order_id).execute()
            return {"status": "error", "message": "Payment initialization failed"}

        return {
            "status":      "created",
            "order_id":    order_id,
            "reference":   reference,
            "pay_amount":  agent_price,
            "payment_url": pay_data["data"]["authorization_url"]
        }
    except Exception as e:
        logger.error("STORE ORDER ERROR: %s", str(e))
        return {"status": "error", "message": "Failed to create order"}


@router.post("/store/order/checker")
@limiter.limit("10/minute")
async def create_store_checker_order(request: Request, payload: CheckerStoreOrderRequest):
    try:
        agent_id       = payload.agent_id
        checker_type   = payload.checker_type
        phone_number   = payload.phone_number
        quantity       = payload.quantity
        customer_email = str(payload.email or "customer@evoshub.store").strip()

        agent = supabase.table("users") \
            .select("id,role,agent_status,full_name,username") \
            .eq("id", agent_id).limit(1).execute()
        if not agent.data:
            return {"status": "error", "message": "Store not found"}
        user = agent.data[0]
        if user.get("role") != "agent" or user.get("agent_status") != "approved":
            return {"status": "error", "message": "Store unavailable"}

        products = get_checker_products()
        product = next((p for p in products if p.get("name", "").upper() == checker_type), None)
        if not product:
            return {"status": "error", "message": "Checker type not available"}
        if not product.get("inStock"):
            return {"status": "error", "message": f"{checker_type} checkers are currently out of stock"}

        base_price = CHECKER_AGENT_BASE_PRICE

        markup = supabase.table("checker_agent_prices").select("markup") \
            .eq("agent_id", agent_id).eq("checker_type", checker_type).limit(1).execute()
        markup_price = float(markup.data[0].get("markup", 0) or 0) if markup.data else 0.0
        unit_agent_price = round(base_price + markup_price, 2)

        total_base_price  = round(base_price * quantity, 2)
        total_agent_price = round(unit_agent_price * quantity, 2)
        total_profit       = round(total_agent_price - total_base_price, 2)

        reference = f"STORE-CHK-{agent_id}-{uuid.uuid4().hex[:10].upper()}"

        checker = supabase.table("checkers").insert({
            "agent_id":     agent_id,
            "guest_email":  customer_email,
            "checker_type": checker_type,
            "phone_number": phone_number,
            "quantity":     quantity,
            "price":        total_agent_price,
            "paystack_ref": reference,
            "evosdata_ref": reference,
            "status":       "pending_payment",
            "base_price":   total_base_price,
            "agent_price":  total_agent_price,
            "profit":       total_profit
        }).execute()

        if not checker.data:
            return {"status": "error", "message": "Failed to create order"}

        checker_id = checker.data[0]["id"]

        pay = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json={
                "email":        customer_email,
                "amount":       int(total_agent_price * 100),
                "reference":    reference,
                "callback_url": f"{callback_base(request)}/store/{agent_id}",
                "metadata":     {"checker_id": checker_id, "agent_id": agent_id, "checker_type": checker_type, "quantity": quantity}
            },
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
            timeout=30
        )
        pay_data = pay.json()

        if not pay_data.get("status"):
            supabase.table("checkers").delete().eq("id", checker_id).execute()
            return {"status": "error", "message": "Payment initialization failed"}

        return {
            "status":      "created",
            "checker_id":  checker_id,
            "reference":   reference,
            "pay_amount":  total_agent_price,
            "payment_url": pay_data["data"]["authorization_url"]
        }
    except Exception as e:
        logger.error("STORE CHECKER ORDER ERROR: %s", str(e))
        return {"status": "error", "message": "Failed to create order"}


# =========================
# AUTH
# =========================
@router.post("/auth/register")
@limiter.limit("5/minute")
def register(request: Request, data: RegisterRequest):
    try:
        username = data.username
        email    = str(data.email).strip().lower()
        phone    = data.phone

        existing_user = supabase.table("users").select("id").eq("username", username).limit(1).execute()
        if existing_user.data:
            return {"status": "username_taken"}

        existing_email = supabase.table("users").select("id").eq("email", email).limit(1).execute()
        if existing_email.data:
            return {"status": "email_taken"}

        try:
            hashed_password = pwd_context.hash(str(data.password))
        except Exception as e:
            logger.error("HASH ERROR: %s", repr(e))
            raise HTTPException(status_code=500, detail="Password hashing failed")

        referral_code = f"{username}_{phone[-4:]}" if len(phone) >= 4 else username

        insert = supabase.table("users").insert({
            "username":      username,
            "full_name":     data.full_name.strip(),
            "email":         email,
            "phone":         phone,
            "password":      hashed_password,
            "referred_by":   data.referred_by,
            "referral_code": referral_code,
            "order_count":   0,
            "rank":          1
        }).execute()

        if not insert.data:
            raise HTTPException(status_code=500, detail="User creation failed")

        return {"status": "created", "email": email, "username": username, "referral_code": referral_code}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("REGISTER ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Server error")


@router.post("/auth/login")
@limiter.limit("10/minute")
def login(request: Request, data: LoginRequest):
    try:
        username = (data.username or "").strip().lower()
        if not username:
            raise HTTPException(status_code=400, detail="Username required")

        user_res = supabase.table("users") \
            .select("*") \
            .or_(f"username.eq.{username},email.eq.{username}") \
            .limit(1) \
            .execute()

        dummy_hash = "$2b$12$KIXzCq3C3T6tFkUd9nj6aO.WwSIFqh4fQieFzpxKx5Mj5.z1rklHC"
        stored_password = user_res.data[0].get("password") if user_res.data else dummy_hash

        try:
            password_ok = pwd_context.verify(data.password, stored_password)
        except Exception:
            password_ok = False

        if not user_res.data or not password_ok:
            return {"status": "invalid_credentials"}

        user = user_res.data[0]

        user_data = {
            "id":            user.get("id"),
            "username":      user.get("username"),
            "email":         user.get("email"),
            "full_name":     user.get("full_name"),
            "referral_code": user.get("referral_code"),
            "rank":          user.get("rank", 1),
            "role":          user.get("role", "user"),
            "agent_status":  user.get("agent_status", "pending"),
            "user_token":    make_user_token(user["id"]),
            "agent_token":   make_agent_token(user["id"]) if (
                user.get("role") == "agent" and user.get("agent_status") == "approved"
            ) else None,
        }
        return {"status": "ok", "user": user_data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("LOGIN ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Server error")


# =========================
# HUB SESSION -> EVOS DATA ACCOUNT
# The embedded app calls this once with the Hub session token. The token is
# verified server-side; the account is loaded from the shared `users` table
# (same ids as before); role / agent_status come from the database. The Hub
# token itself is returned as user_token / agent_token, so there is exactly
# one session for the whole ecosystem — it expires with the Hub session and
# no separate long-lived Evosdata token is minted.
# =========================
@router.post("/auth/hub-session")
@limiter.limit("30/minute")
def hub_session(request: Request, authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    uid = _hub_session_uid(token)
    if uid is None:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    try:
        res = supabase.table("users").select("*").eq("id", uid).limit(1).execute()
    except Exception as e:
        logger.error("HUB SESSION USER LOOKUP ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Server error")
    if not res.data:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    user = res.data[0]
    is_agent = user.get("role") == "agent" and user.get("agent_status") == "approved"
    return {"status": "ok", "user": {
        "id":            user.get("id"),
        "username":      user.get("username"),
        "email":         user.get("email"),
        "full_name":     user.get("full_name"),
        "referral_code": user.get("referral_code"),
        "rank":          user.get("rank", 1),
        "role":          user.get("role", "user"),
        "agent_status":  user.get("agent_status", "pending"),
        "user_token":    token,
        "agent_token":   token if is_agent else None,
    }}


# =========================
# ADMIN LOGIN (admin_agents-gated — DashXera and any other internal tool)
#
# Same public.users credentials as customer/agent login above. A correct
# password alone is not enough: the account must also have an active row
# in admin_agents. This is the exact scheme already running in evoshub and
# XERA (see admin_auth.py) — one account works across the whole ecosystem.
# =========================

from services.evosdata.admin_auth import (
    AdminTokenInvalid,
    clear_failures,
    is_locked,
    make_admin_token,
    record_failure,
    require_active_admin,
)

_ADMIN_DUMMY_HASH = "$2b$12$KIXzCq3C3T6tFkUd9nj6aO.WwSIFqh4fQieFzpxKx5Mj5.z1rklHC"
_ADMIN_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._%+\-@]{1,120}$")


class AdminLoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=120, description="Username or email")
    password: str = Field(..., min_length=1, max_length=200)


@router.post("/admin/login")
@limiter.limit("10/minute")
def admin_login(request: Request, data: AdminLoginRequest):
    identifier = data.identifier.strip().lower()
    if not _ADMIN_IDENTIFIER_RE.match(identifier):
        return {"status": "invalid_credentials"}
    ip = get_remote_address(request)

    # Both lockout dimensions are checked before any DB or bcrypt work runs.
    id_locked, id_remaining = is_locked(f"id:{identifier}")
    ip_locked, ip_remaining = is_locked(f"ip:{ip}")
    if id_locked or ip_locked:
        retry_after = max(id_remaining, ip_remaining)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {retry_after} seconds.",
        )

    user_res = (
        supabase.table("users").select("*")
        .or_(f"username.eq.{identifier},email.eq.{identifier}")
        .limit(1).execute()
    )
    user = user_res.data[0] if user_res.data else None
    stored_hash = user.get("password") if user else _ADMIN_DUMMY_HASH

    try:
        password_ok = pwd_context.verify(data.password, stored_hash)
    except Exception:
        password_ok = False

    if not user or not password_ok:
        record_failure(f"id:{identifier}")
        record_failure(f"ip:{ip}")
        return {"status": "invalid_credentials"}

    agent_res = (
        supabase.table("admin_agents").select("is_active, display_name")
        .eq("user_id", user["id"]).limit(1).execute()
    )
    agent = agent_res.data[0] if agent_res.data else None
    if not agent or not agent.get("is_active"):
        # Correct password but not an active admin agent. Still counted as a
        # failure against both counters — valid credentials plus repeated
        # attempts is exactly the "found the password, testing authorization"
        # pattern lockout exists to slow down.
        record_failure(f"id:{identifier}")
        record_failure(f"ip:{ip}")
        return {"status": "not_authorized"}

    clear_failures(f"id:{identifier}")
    clear_failures(f"ip:{ip}")

    token = make_admin_token(user["id"])
    return {
        "status": "ok",
        "token": token,
        "user": {
            "id": user["id"],
            "username": user.get("username"),
            "display_name": agent.get("display_name") or user.get("full_name"),
        },
    }


@router.get("/admin/me")
@limiter.limit("60/minute")
def admin_me(request: Request, authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id, display_name = require_active_admin(supabase, token)
    except AdminTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access has been revoked.")
    return {"status": "ok", "user": {"id": user_id, "display_name": display_name}}


# =========================
# TODAY DASHBOARD
# =========================
@router.get("/today/{user_id}")
@limiter.limit("30/minute")
def today_dashboard(request: Request, user_id: int):
    require_user(request, user_id)  # token must belong to this user_id
    try:
        global_orders = supabase.table("orders").select("id", count="exact").execute()
        total_orders  = global_orders.count or 0

        user_orders = supabase.table("orders") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .execute()
        my_orders = user_orders.data or []

        success_status = ["processing", "successful", "delivered", "initiated"]
        my_successful_orders = [o for o in my_orders if o["status"] in success_status]

        transactions = [
            {
                "network":      row["network"],
                "amount":       f'{row["bundle"]} - GHS {row["price"]}',
                "phone_number": row["phone_number"],
                "evosdata_ref": row["evosdata_ref"],
                "paystack_ref": row["paystack_ref"],
                "datamart_ref": row["datamart_ref"],
                "status":       row["status"],
                "created_at":   row["created_at"]
            }
            for row in my_orders
        ]

        return {
            "global": {"total_orders": total_orders},
            "user": {
                "my_orders":            len(my_orders),
                "my_successful_orders": len(my_successful_orders),
                "transactions":         transactions
            }
        }
    except Exception as e:
        logger.error("TODAY ERROR: %s", str(e))
        raise HTTPException(500, "Server error")


# =========================
# USSD
# =========================
@router.post("/ussd")
@limiter.limit("30/minute")
async def ussd(request: Request):
    data = await request.json()
    phone        = data.get("phoneNumber")
    text         = data.get("text", "")
    user_input   = text.split("*") if text else []

    if text == "":
        return (
            "CON Welcome to EVOS Business Hub\n"
            "1. Buy Data\n"
            "2. My Orders\n"
            "3. Support\n"
        )

    if user_input[0] == "1":
        if len(user_input) == 1:
            return "CON Select Network\n1. MTN\n2. Telecel\n3. AirtelTigo"

        network_map = {"1": "MTN", "2": "TELECEL", "3": "AIRTELTIGO"}
        network = network_map.get(user_input[1])
        if not network:
            return "END Invalid network selected"

        if len(user_input) == 2:
            return f"CON {network} Bundles\n1. 1GB - GH₵5\n2. 2GB - GH₵10\n3. 5GB - GH₵20"

        bundle_map = {"1": ("1GB", 5), "2": ("2GB", 10), "3": ("5GB", 20)}
        bundle_data = bundle_map.get(user_input[2])
        if not bundle_data:
            return "END Invalid bundle selected"

        bundle, price = bundle_data

        try:
            price_res = supabase.table("prices").select("price").eq("network", network).eq("bundle", bundle).limit(1).execute()
            if not price_res.data:
                return "END Bundle not available"
            if not datamart_stock.bundle_in_stock(network, bundle):
                return "END Sorry, that bundle is out of stock. Try a smaller one or check back soon."

            actual_price = float(price_res.data[0]["price"])
            paystack = requests.post(
                "https://api.paystack.co/transaction/initialize",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
                json={"email": f"{phone}@evosdata.ussd", "amount": int(actual_price * 100), "callback_url": "https://evosdata.xyz/success"},
                timeout=REQUEST_TIMEOUT
            ).json()

            if not paystack.get("status"):
                return "END Payment init failed. Try again."

            ref      = paystack["data"]["reference"]
            evos_ref = f"EVOS-{uuid.uuid4().hex[:8].upper()}"

            supabase.table("orders").insert({
                "network":      network,
                "bundle":       bundle,
                "price":        actual_price,
                "phone_number": phone,
                "status":       "pending_payment",
                "evosdata_ref": evos_ref,
                "paystack_ref": ref
            }).execute()

            return (
                f"END Order Created\n"
                f"Network: {network}\n"
                f"Bundle: {bundle}\n"
                f"Pay: {paystack['data']['authorization_url']}"
            )
        except Exception as e:
            logger.error("USSD ERROR: %s", str(e))
            return "END Service temporarily unavailable"

    if user_input[0] == "2":
        return "END Check orders at:\nhttps://evosdata.netlify.app"

    if user_input[0] == "3":
        return "END EVOS Support:\nWhatsApp: +233537314125"

    return "END Invalid request"


# =========================
# FORGOT / RESET PASSWORD
# =========================
import random

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=6, max_length=128)


@router.post("/auth/forgot-password")
@limiter.limit("3/minute")
def forgot_password(request: Request, data: ForgotPasswordRequest):
    try:
        email = str(data.email).strip().lower()

        user_res = supabase.table("users") \
            .select("id, full_name, email") \
            .ilike("email", email) \
            .limit(1) \
            .execute()

        if not user_res.data:
            _otp_log("FORGOT PASSWORD: no account matches %s", _mask_email(email))
            return {"status": "sent", "message": "If that email exists, an OTP has been sent."}

        user    = user_res.data[0]
        _otp_log("FORGOT PASSWORD: account found for %s (user %s), sending OTP", _mask_email(email), user["id"])
        user_id = user["id"]

        supabase.table("password_resets") \
            .update({"used": True}) \
            .eq("user_id", user_id) \
            .eq("used", False) \
            .execute()

        otp        = str(random.randint(100000, 999999))
        expires_at = (utc_now() + timedelta(minutes=10)).isoformat()

        supabase.table("password_resets").insert({
            "user_id":    user_id,
            "otp":        otp,
            "expires_at": expires_at,
            "used":       False,
        }).execute()

        sent = send_otp_email(
            to_email  = user["email"],
            otp       = otp,
            full_name = user.get("full_name", "User")
        )

        if not sent:
            _otp_log("FORGOT PASSWORD: email failed for user %s", user_id)

        return {"status": "sent", "message": "If that email exists, an OTP has been sent."}

    except Exception as e:
        _otp_log("FORGOT PASSWORD ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Server error")


@router.post("/auth/verify-otp")
@limiter.limit("5/minute")
def verify_otp(request: Request, data: VerifyOTPRequest):
    try:
        email = str(data.email).strip().lower()

        user_res = supabase.table("users") \
            .select("id") \
            .ilike("email", email) \
            .limit(1) \
            .execute()

        if not user_res.data:
            raise HTTPException(status_code=400, detail="Invalid OTP")

        user_id = user_res.data[0]["id"]

        reset_res = supabase.table("password_resets") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("otp", data.otp) \
            .eq("used", False) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if not reset_res.data:
            raise HTTPException(status_code=400, detail="Invalid OTP")

        reset      = reset_res.data[0]
        expires_at = parse_db_dt(reset["expires_at"])

        if utc_now() > expires_at:
            raise HTTPException(status_code=400, detail="OTP has expired")

        return {"status": "valid", "message": "OTP verified. You may now reset your password."}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("VERIFY OTP ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Server error")


@router.post("/auth/reset-password")
@limiter.limit("5/minute")
def reset_password(request: Request, data: ResetPasswordRequest):
    try:
        email = str(data.email).strip().lower()

        user_res = supabase.table("users") \
            .select("id") \
            .ilike("email", email) \
            .limit(1) \
            .execute()

        if not user_res.data:
            raise HTTPException(status_code=400, detail="Invalid request")

        user_id = user_res.data[0]["id"]

        reset_res = supabase.table("password_resets") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("otp", data.otp) \
            .eq("used", False) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if not reset_res.data:
            raise HTTPException(status_code=400, detail="Invalid OTP")

        reset      = reset_res.data[0]
        expires_at = parse_db_dt(reset["expires_at"])

        if utc_now() > expires_at:
            raise HTTPException(status_code=400, detail="OTP has expired")

        new_hashed = hash_password(data.new_password)
        supabase.table("users") \
            .update({"password": new_hashed}) \
            .eq("id", user_id) \
            .execute()

        supabase.table("password_resets") \
            .update({"used": True}) \
            .eq("id", reset["id"]) \
            .execute()

        logger.info("RESET PASSWORD: user %s reset their password", user_id)
        return {"status": "success", "message": "Password reset successfully. You can now log in."}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("RESET PASSWORD ERROR: %s", str(e))
        raise HTTPException(status_code=500, detail="Server error")


# =========================
# WHATSAPP WEBHOOK
# NOTE: In-memory sessions reset on restart.
#       For persistence, migrate sessions to Supabase or Redis.
# =========================
from fastapi.responses import Response

sessions: dict = {}

def get_session(phone: str):
    if phone not in sessions:
        sessions[phone] = {"step": "start", "network": None, "bundle": None, "price": None}
    return sessions[phone]

def fetch_price(network: str, bundle: str):
    res = supabase.table("prices").select("price").eq("network", network).eq("bundle", bundle).limit(1).execute()
    if not res.data:
        return None
    return float(res.data[0]["price"])

def init_paystack(email: str, amount: float):
    res = requests.post(
        "https://api.paystack.co/transaction/initialize",
        headers={"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"},
        json={"email": email, "amount": int(amount * 100), "callback_url": "https://evosdata.netlify.app/success"}
    )
    data = res.json()
    if not data.get("status"):
        return None
    return data["data"]

@router.post("/whatsapp/webhook")
@limiter.limit("20/minute")
async def whatsapp_webhook(request: Request):
    form    = await request.form()
    message = form.get("Body", "").strip().lower()
    phone   = form.get("From")

    session = get_session(phone)
    reply   = ""

    if message in ["hi", "hello", "start", "menu"]:
        session["step"] = "menu"
        reply = "👋 *EVOS DATA HUB*\n\n1️⃣ Buy Data\n2️⃣ Track Order\n3️⃣ Support"
    elif message == "1" and session["step"] == "menu":
        session["step"] = "network"
        reply = "📡 Select Network:\n\n1️⃣ MTN\n2️⃣ Telecel\n3️⃣ AirtelTigo"
    elif message in ["1", "mtn"] and session["step"] == "network":
        session["network"] = "MTN"
        session["step"]    = "bundle"
        reply = "📦 Send MTN bundle (e.g. 1GB, 2GB)"
    elif message in ["2", "telecel"] and session["step"] == "network":
        session["network"] = "TELECEL"
        session["step"]    = "bundle"
        reply = "📦 Send Telecel bundle"
    elif message in ["3", "airteltigo"] and session["step"] == "network":
        session["network"] = "AIRTELTIGO"
        session["step"]    = "bundle"
        reply = "📦 Send AirtelTigo bundle"
    elif session["step"] == "bundle":
        session["bundle"] = message.upper()
        price = fetch_price(session["network"], session["bundle"])
        if not price:
            reply = "❌ Bundle not found. Try again."
        elif not datamart_stock.bundle_in_stock(session["network"], session["bundle"]):
            reply = "❌ That bundle is out of stock right now. Try a smaller one or check back soon."
        else:
            session["price"] = price
            session["step"]  = "confirm"
            reply = f"📦 *ORDER SUMMARY*\n\nNetwork: {session['network']}\nBundle: {session['bundle']}\nPrice: GHS {price}\n\n1️⃣ Confirm & Pay\n2️⃣ Cancel"
    elif message == "1" and session["step"] == "confirm":
        evos_ref = f"EVOS-{uuid.uuid4().hex[:8].upper()}"
        paystack = init_paystack(email=f"{phone}@evosdata.com", amount=session["price"])
        if not paystack:
            reply = "❌ Payment initialization failed."
        else:
            paystack_ref = paystack["reference"]
            supabase.table("orders").insert({
                "network":      session["network"],
                "bundle":       session["bundle"],
                "price":        session["price"],
                "phone_number": phone,
                "status":       "pending_payment",
                "evosdata_ref": evos_ref,
                "paystack_ref": paystack_ref
            }).execute()
            reply = f"💳 *PAYMENT READY*\n\nAmount: GHS {session['price']}\n\nPay here:\n{paystack['authorization_url']}\n\nData delivered automatically after payment."
            session["step"] = "done"
    elif message == "2":
        session["step"] = "menu"
        reply = "❌ Order cancelled. Type *menu* to restart."
    elif message == "3":
        reply = "💬 Support: https://wa.me/233537314125"
    else:
        reply = "❌ Invalid input. Type *menu*."

    xml = f"<Response><Message>{reply}</Message></Response>"
    return Response(content=xml, media_type="application/xml")


@router.get("/")
def root():
    return {"status": "EVOS Data API is running"}
