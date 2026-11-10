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
from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field, field_validator

from services import website_orders as orders
from utils.supabase_admin import (
    VisitorTokenInvalid,
    get_website_request,
    insert_visitor_chat_message,
    insert_website_request,
    list_chat_messages,
    patch_website_request,
    verify_visitor_token,
)
from xera.payments.base import PaymentProviderError
from utils.email_sender import send_email
from utils.rate_limit import limiter
from utils.text_sanitize import clean_text as _clean_text

router = APIRouter()

_ALLOWED_PACKAGES = {"starter", "business", "premium", "whatsapp_bot", "custom"}


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
        "message": "Thanks! Your request is in.",
        "request_id": inserted.get("id"),
        "pricing": orders.package_pricing(payload.package),   # None for quote-only packages
        "methods": orders.methods_available(),
    }


# ---------------------------------------------------------------------------------
# Pricing, files, payment, receipt
# ---------------------------------------------------------------------------------

async def _visitor_id(authorization: str) -> str:
    try:
        return await verify_visitor_token(authorization.removeprefix("Bearer ").strip())
    except VisitorTokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please refresh and try again.")


async def _own_request(request_id: str, authorization: str) -> dict:
    """The request row, only if it belongs to the verified visitor (404 otherwise, never a hint)."""
    visitor = await _visitor_id(authorization)
    row = await get_website_request(request_id=request_id)
    if not row or row.get("visitor_id") != visitor:
        raise HTTPException(status_code=404, detail="Request not found.")
    return row


def _xera_user_id(x_xera_authorization: str) -> int | None:
    """Optional XERA session (separate from the visitor session). Bad/missing token = not signed in."""
    token = x_xera_authorization.removeprefix("Bearer ").strip()
    if not token:
        return None
    try:
        from xera.user_auth import verify_user_token, XeraTokenInvalid
        try:
            return verify_user_token(token)
        except XeraTokenInvalid:
            return None
    except Exception:
        return None


def _order_error(e: "orders.WebsiteOrderError"):
    raise HTTPException(status_code=e.status, detail=e.message)


@router.get("/website-requests/pricing")
@limiter.limit("60/minute")
async def website_pricing(request: Request):
    """Public price cards (list price, discounted price, XERA saving) so the page never hard-codes prices."""
    return {"packages": orders.all_pricing(), "methods": orders.methods_available()}


@router.post("/website-requests/{request_id}/files")
@limiter.limit("40/hour")
async def upload_request_file(
    request: Request,
    request_id: str,
    file: UploadFile = File(...),
    authorization: str = Header(default=""),
):
    await _own_request(request_id, authorization)
    # Read one byte past the cap so an oversize file is rejected without buffering all of it.
    content = await file.read(orders.MAX_FILE_BYTES + 1)
    try:
        saved = await orders.save_upload(request_id, file.filename or "", content)
    except orders.WebsiteOrderError as e:
        _order_error(e)
    except Exception as e:
        print(f"[WEBSITE-UPLOAD ERROR] {e}")
        raise HTTPException(status_code=502, detail="Could not save that file. Please try again.")
    return {"status": "ok", "file": saved}


@router.post("/website-requests/{request_id}/talk-first")
@limiter.limit("20/hour")
async def choose_talk_first(request: Request, request_id: str, authorization: str = Header(default="")):
    row = await _own_request(request_id, authorization)
    if row.get("payment_status") != "paid" and row.get("contact_path") != "talk":
        await patch_website_request(request_id, {"contact_path": "talk"})
    return {"status": "ok"}


@router.get("/website-requests/{request_id}/payment")
@limiter.limit("60/minute")
async def payment_state(
    request: Request,
    request_id: str,
    authorization: str = Header(default=""),
    x_xera_authorization: str = Header(default=""),
):
    """
    Everything the pay step needs in one call: price card, which methods work, the XERA
    quote for this visitor, and the live payment status. Also reconciles a pending Paystack
    payment directly with Paystack, so the page does not depend on the webhook being fast.
    """
    row = await _own_request(request_id, authorization)
    row = await orders.reconcile_paystack(row)
    pricing = orders.package_pricing(row["package"])

    xera = None
    if pricing and row.get("payment_status") != "paid":
        try:
            from main import supabase as sb
            q = await run_in_threadpool(orders.xera_quote, sb, _xera_user_id(x_xera_authorization), pricing["price"])
            xera = {k: v for k, v in q.items() if not k.startswith("_")}
        except Exception as exc:
            print(f"[WEBSITE-XERA QUOTE WARNING] {exc}")

    return {
        "status": row.get("payment_status", "unpaid"),
        "payment_method": row.get("payment_method"),
        "receipt_no": row.get("receipt_no"),
        "package": row["package"],
        "pricing": pricing,
        "methods": orders.methods_available(),
        "xera": xera,
    }


class PayIn(BaseModel):
    method: str = Field(..., min_length=1, max_length=20)
    use_xera: bool = False


@router.post("/website-requests/{request_id}/pay")
@limiter.limit("10/hour")
async def pay_for_request(
    request: Request,
    request_id: str,
    data: PayIn,
    authorization: str = Header(default=""),
    x_xera_authorization: str = Header(default=""),
):
    row = await _own_request(request_id, authorization)
    try:
        return await orders.start_payment(
            row,
            method=data.method.strip().lower(),
            use_xera=data.use_xera,
            xera_user_id=_xera_user_id(x_xera_authorization),
        )
    except orders.WebsiteOrderError as e:
        _order_error(e)
    except PaymentProviderError as e:
        print(f"[WEBSITE-PAY PROVIDER ERROR] {request_id}: {e}")
        raise HTTPException(status_code=502, detail="The payment provider is unavailable right now. Please try again shortly.")


@router.get("/website-requests/{request_id}/receipt")
@limiter.limit("30/minute")
async def get_receipt(request: Request, request_id: str, authorization: str = Header(default="")):
    row = await _own_request(request_id, authorization)
    try:
        return {"receipt": orders.build_receipt(row)}
    except orders.WebsiteOrderError as e:
        _order_error(e)


# ---------------------------------------------------------------------------------
# Customer chat. Goes through the backend (service role) after verifying the request
# belongs to the visitor, so it works even if browser-side database access does not.
# ---------------------------------------------------------------------------------

class ChatMessageIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


def _public_message(m: dict) -> dict:
    return {"id": m.get("id"), "sender_role": m.get("sender_role"), "body": m.get("body"), "created_at": m.get("created_at")}


@router.get("/website-requests/{request_id}/messages")
@limiter.limit("120/minute")
async def visitor_list_messages(request: Request, request_id: str, authorization: str = Header(default="")):
    await _own_request(request_id, authorization)
    msgs = await list_chat_messages(request_id)
    return {"status": "ok", "messages": [_public_message(m) for m in msgs]}


@router.post("/website-requests/{request_id}/messages")
@limiter.limit("20/minute")
async def visitor_send_message(
    request: Request, request_id: str, data: ChatMessageIn, authorization: str = Header(default=""),
):
    row = await _own_request(request_id, authorization)
    body = data.body.strip()  # rendered with textContent on the page, so no HTML escaping here
    if not body:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    msg = await insert_visitor_chat_message(request_id, body, row["visitor_id"])
    return {"status": "ok", "message": _public_message(msg)}
