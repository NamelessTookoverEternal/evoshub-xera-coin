"""
/api/contact — Receives contact form submissions.

Hardened to match website_requests.py: rate limited, honeypot spam trap,
and every free-text field sanitized before it touches an email body or a
log line (an unsanitized name/message with embedded newlines could
otherwise forge extra header lines or fake log entries).
"""

import os

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from utils.email_sender import send_email
from utils.rate_limit import limiter
from utils.text_sanitize import clean_text

router = APIRouter()


class ContactMessage(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    message: str = Field(..., min_length=1, max_length=4000)

    # Honeypot — real visitors never see or fill this (hidden off-screen in
    # CSS on the frontend, not display:none, so bots that skip display:none
    # fields still get caught).
    website: str | None = Field(default=None, max_length=200)

    @field_validator("name", "message")
    @classmethod
    def _sanitize(cls, v):
        return clean_text(v)


@router.post("/contact")
@limiter.limit("10/hour")
async def send_contact(request: Request, data: ContactMessage):
    # Spam trap: pretend success, do nothing.
    if data.website:
        return {"status": "received", "message": "Thank you! We'll be in touch soon."}

    print(f"[CONTACT] {data.name} <{data.email}>: {data.message}")

    try:
        send_email(
            to=os.getenv("ADMIN_NOTIFY_EMAIL", os.getenv("EMAIL_USER", "")),
            subject=f"New contact form message from {data.name}",
            body=f"From: {data.name} <{data.email}>\n\n{data.message}",
        )
    except Exception as e:
        # Best-effort — a failed notification email never fails the
        # visitor's submission.
        print(f"[CONTACT EMAIL WARNING] {e}")

    return {"status": "received", "message": "Thank you! We'll be in touch soon."}
