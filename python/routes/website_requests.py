"""
/api/website-requests — Website Creation product intake form.

Flow:
  1. Browser calls supabase.auth.signInAnonymously() and gets a real,
     Supabase-issued access token (see hub-frontend/src/js/supabase-client.js).
  2. Browser POSTs the form here with that token in the Authorization header.
  3. We verify the token against Supabase's Auth server (never trust a
     client-supplied user id), validate + sanitize the payload, apply rate
     limiting and a honeypot spam check, then insert the row ourselves using
     the service_role key so the DB-level constraints are the only other
     line of defense.
  4. We best-effort email the admin team. A failure to send email never
     fails the visitor's request.
"""

import os
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from utils.supabase_admin import (
    VisitorTokenInvalid,
    insert_website_request,
    verify_visitor_token,
)
from utils.email_sender import send_email
from utils.rate_limit import limiter
from utils.text_sanitize import clean_text as _clean_text

router = APIRouter()

_ALLOWED_PACKAGES = {"starter", "business", "premium", "custom"}


class WebsiteRequestIn(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    business_name: str | None = Field(default=None, max_length=160)
    package: str
    budget_range: str | None = Field(default=None, max_length=60)
    timeline: str | None = Field(default=None, max_length=60)
    project_brief: str = Field(..., min_length=1, max_length=4000)

    # Honeypot — a real visitor never sees or fills this field (hidden via
    # CSS off-screen, not display:none, to also dodge bots that skip
    # display:none fields). Any value here means we're talking to a bot.
    website: str | None = Field(default=None, max_length=200)

    @field_validator("full_name", "business_name", "budget_range", "timeline", "project_brief", "phone")
    @classmethod
    def _sanitize(cls, v):
        if v is None:
            return v
        return _clean_text(v)

    @field_validator("package")
    @classmethod
    def _check_package(cls, v):
        v = v.strip().lower()
        if v not in _ALLOWED_PACKAGES:
            raise ValueError("Invalid package selection.")
        return v


@router.post("/website-requests")
@limiter.limit("5/hour")
async def create_website_request(
    request: Request,
    payload: WebsiteRequestIn,
    authorization: str = Header(default=""),
):
    # --- spam trap: pretend success, insert nothing ---
    if payload.website:
        return {"status": "received", "message": "Thanks! We'll be in touch soon."}

    # --- verify the visitor's Supabase session (never trust a client id) ---
    token = authorization.removeprefix("Bearer ").strip()
    try:
        visitor_id = await verify_visitor_token(token)
    except VisitorTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please refresh and try again.")

    row = {
        "visitor_id": visitor_id,
        "full_name": payload.full_name,
        "email": str(payload.email),
        "phone": payload.phone,
        "business_name": payload.business_name,
        "package": payload.package,
        "budget_range": payload.budget_range,
        "timeline": payload.timeline,
        "project_brief": payload.project_brief,
    }

    try:
        inserted = await insert_website_request(row)
    except Exception as e:
        print(f"[WEBSITE-REQUEST ERROR] {e}")
        raise HTTPException(status_code=502, detail="Could not save your request. Please try again shortly.")

    # Best-effort admin notification — never fails the visitor's request.
    try:
        send_email(
            to=os.getenv("ADMIN_NOTIFY_EMAIL", os.getenv("EMAIL_USER", "")),
            subject=f"New Website Creation request — {payload.full_name}",
            body=(
                f"Package: {payload.package}\n"
                f"Name: {payload.full_name}\n"
                f"Email: {payload.email}\n"
                f"Phone: {payload.phone or '-'}\n"
                f"Business: {payload.business_name or '-'}\n"
                f"Budget: {payload.budget_range or '-'}\n"
                f"Timeline: {payload.timeline or '-'}\n\n"
                f"Brief:\n{payload.project_brief}\n\n"
                f"Request ID: {inserted.get('id')}\n"
            ),
        )
    except Exception as e:
        print(f"[WEBSITE-REQUEST EMAIL WARNING] {e}")

    return {
        "status": "received",
        "message": "Thanks! Your request is in. You can chat with our team now.",
        "request_id": inserted.get("id"),
    }
