"""
Become-an-agent fee (GH₵50, was GH₵100).

Mounted at the bottom of main.py like spin.py:

    import agent_fee
    agent_fee.install(app)

Flow (as agreed with the owner):
  1. The customer pays GH₵50 on Paystack. The AMOUNT IS SET HERE on the server.
  2. About 30 minutes after the payment, the server verifies it with Paystack again
     and, only if it is still a successful payment, upgrades the account:
         users.role = 'agent', users.agent_status = 'approved'
     Nobody has to approve it by hand.
  3. A background job (every minute) does the waiting, so closing the page, a restart
     or a late Paystack webhook cannot leave anyone who paid without activation.
     It follows the same rules as your wallet-deposit retry job: the status flip is an
     atomic claim, so an account is activated exactly once.

Endpoints (X-User-Token required, issued at login):
    GET  /agent-fee/info
    POST /agent-fee/initiate   {user_id}
    GET  /agent-fee/status?user_id=&reference=
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("agent_fee")

AGENT_FEE = 50.00
AGENT_FEE_WAS = 100.00
ACTIVATION_DELAY_MIN = 30          # wait this long after payment, then verify and activate
UNPAID_CHECK_EVERY_MIN = 5         # how often an unpaid attempt is re-checked with Paystack
EXPIRE_UNPAID_AFTER_HOURS = 24     # an attempt nobody paid for is closed after this
LOOP_SECONDS = 60

_MAIN_MODULE_NAME = "services.evosdata.core"


def _main():
    mod = sys.modules.get(_MAIN_MODULE_NAME)
    if mod is not None:
        return mod
    return importlib.import_module(_MAIN_MODULE_NAME)


def _db():
    return _main().supabase


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(raw) -> datetime:
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _paystack_verify(reference: str) -> dict:
    m = _main()
    res = requests.get(
        f"https://api.paystack.co/transaction/verify/{reference}",
        headers={"Authorization": f"Bearer {m.PAYSTACK_SECRET}"},
        timeout=m.REQUEST_TIMEOUT,
    ).json()
    return res.get("data") or {} if res.get("status") else {}


def _is_agent(user: dict) -> bool:
    return user.get("role") == "agent" and user.get("agent_status") == "approved"


# ============================================================================
# CORE: process one payment row. Used by the status endpoint and the background job.
# ============================================================================

def process_payment(row: dict) -> dict:
    """Advance one agent_fee_payments row as far as it can go right now. Returns the fresh row."""
    db = _db()
    now = _now()
    if row["status"] in ("activated", "failed", "expired"):
        return row

    if row["status"] == "pending":
        data = _paystack_verify(row["reference"])
        pstatus = data.get("status")
        if pstatus == "success":
            # Only trust the amount Paystack actually took (kobo/pesewas).
            if int(data.get("amount", 0)) < int(round(float(row["amount"]) * 100)):
                db.table("agent_fee_payments").update({"status": "failed", "last_checked_at": now.isoformat()}) \
                    .eq("id", row["id"]).eq("status", "pending").execute()
                logger.error("AGENT FEE: %s underpaid (%s)", row["reference"], data.get("amount"))
                return {**row, "status": "failed"}
            paid_at = _parse_dt(data["paid_at"]) if data.get("paid_at") else now
            upd = {"status": "paid", "paid_at": paid_at.isoformat(), "last_checked_at": now.isoformat(),
                   "activate_after": (paid_at + timedelta(minutes=ACTIVATION_DELAY_MIN)).isoformat()}
            db.table("agent_fee_payments").update(upd).eq("id", row["id"]).eq("status", "pending").execute()
            row = {**row, **upd}
            logger.info("AGENT FEE: %s paid, activation due %s", row["reference"], upd["activate_after"])
        elif pstatus in ("failed", "reversed"):
            db.table("agent_fee_payments").update({"status": "failed", "last_checked_at": now.isoformat()}) \
                .eq("id", row["id"]).eq("status", "pending").execute()
            return {**row, "status": "failed"}
        else:
            # abandoned / ongoing / not found: keep waiting, close it after a day
            upd = {"last_checked_at": now.isoformat()}
            if now - _parse_dt(row["created_at"]) > timedelta(hours=EXPIRE_UNPAID_AFTER_HOURS):
                upd["status"] = "expired"
            db.table("agent_fee_payments").update(upd).eq("id", row["id"]).eq("status", "pending").execute()
            return {**row, **upd}

    if row["status"] == "paid" and row.get("activate_after") and now >= _parse_dt(row["activate_after"]):
        # "...then verify": confirm with Paystack once more right before upgrading.
        data = _paystack_verify(row["reference"])
        if data.get("status") != "success":
            logger.error("AGENT FEE: %s no longer verifies at activation time (%s)", row["reference"], data.get("status"))
            db.table("agent_fee_payments").update({"status": "failed"}).eq("id", row["id"]).eq("status", "paid").execute()
            return {**row, "status": "failed"}

        # Atomic claim: exactly one caller flips paid -> activated and upgrades the account.
        claim = (db.table("agent_fee_payments")
                 .update({"status": "activated", "activated_at": now.isoformat()})
                 .eq("id", row["id"]).eq("status", "paid").execute())
        if not claim.data:
            return {**row, "status": "activated"}

        user = (db.table("users").select("id,role,agent_status").eq("id", row["user_id"]).limit(1).execute().data or [None])[0]
        if user and user.get("role") != "admin":
            db.table("users").update({"role": "agent", "agent_status": "approved"}).eq("id", row["user_id"]).execute()
        logger.info("AGENT FEE: user %s upgraded to agent (ref %s)", row["user_id"], row["reference"])
        return {**row, "status": "activated", "activated_at": now.isoformat()}

    return row


def _public(row: Optional[dict]) -> dict:
    if not row:
        return {"state": "none"}
    st = row["status"]
    out = {"state": st, "reference": row["reference"]}
    if st == "paid":
        out["activate_after"] = row.get("activate_after")
    return out


# ============================================================================
# API
# ============================================================================

router = APIRouter(prefix="/agent-fee", tags=["agent-fee"])


class InitBody(BaseModel):
    user_id: int


@router.get("/info")
def info():
    return {"fee": AGENT_FEE, "was": AGENT_FEE_WAS, "delay_minutes": ACTIVATION_DELAY_MIN}


@router.post("/initiate")
def initiate(request: Request, body: InitBody):
    m = _main()
    user_id = m.require_user(request, body.user_id)
    db = _db()

    users = db.table("users").select("id,email,role,agent_status").eq("id", user_id).limit(1).execute().data
    if not users:
        raise HTTPException(404, "User not found")
    user = users[0]
    if _is_agent(user):
        return {"status": "already_agent"}
    if user.get("role") == "admin":
        raise HTTPException(400, "Admin accounts cannot become agents")

    # Someone who already paid and is waiting must not pay twice.
    waiting = (db.table("agent_fee_payments").select("*").eq("user_id", user_id)
               .eq("status", "paid").limit(1).execute().data)
    if waiting:
        return {"status": "waiting", **_public(process_payment(waiting[0]))}

    reference = f"EVOS-AGTFEE-{user_id}-{uuid.uuid4().hex[:10].upper()}"
    try:
        res = requests.post(
            "https://api.paystack.co/transaction/initialize",
            headers={"Authorization": f"Bearer {m.PAYSTACK_SECRET}", "Content-Type": "application/json"},
            json={
                "email": user.get("email") or "guest@evoshub.com",
                "amount": int(round(AGENT_FEE * 100)),
                "currency": "GHS",
                "reference": reference,
                "metadata": {"user_id": user_id, "type": "agent_fee"},
                "callback_url": f"{m.callback_base(request)}/success?type=agent-fee&reference={reference}",
            },
            timeout=m.REQUEST_TIMEOUT,
        ).json()
    except requests.exceptions.RequestException:
        raise HTTPException(502, "Payment service error. Please try again.")
    if not res.get("status"):
        raise HTTPException(400, res.get("message") or "Payment init failed")

    db.table("agent_fee_payments").insert({
        "user_id": user_id, "reference": reference, "amount": AGENT_FEE, "status": "pending",
    }).execute()
    return {"status": "created", "reference": reference, "payment_url": res["data"]["authorization_url"]}


@router.get("/status")
def status(request: Request, user_id: int, reference: Optional[str] = None):
    m = _main()
    m.require_user(request, user_id)
    db = _db()

    users = db.table("users").select("id,role,agent_status").eq("id", user_id).limit(1).execute().data
    if users and _is_agent(users[0]):
        # The browser's saved login predates the upgrade and has no agent token, so hand one over
        # here (the caller just proved who they are with their user token) instead of making
        # the new agent sign out and back in.
        return {"state": "activated", "is_agent": True, "agent_token": m.make_agent_token(user_id)}

    q = db.table("agent_fee_payments").select("*").eq("user_id", user_id)
    if reference:
        q = q.eq("reference", reference)
    rows = q.order("created_at", desc=True).limit(1).execute().data
    if not rows:
        return {"state": "none", "is_agent": False}
    row = rows[0]
    # Looking at a pending attempt is also what records "paid" the moment the customer returns.
    if row["status"] in ("pending", "paid"):
        try:
            row = process_payment(row)
        except Exception as e:
            logger.error("AGENT FEE: status check failed for %s: %s", row.get("reference"), e)
    out = {**_public(row), "is_agent": row["status"] == "activated"}
    if out["is_agent"]:
        out["agent_token"] = m.make_agent_token(user_id)
    return out


# ============================================================================
# BACKGROUND JOB: does the 30-minute wait and the activation
# ============================================================================

def run_once() -> int:
    """One pass over open payments. Returns how many rows it looked at."""
    db = _db()
    now = _now()
    n = 0
    open_rows = db.table("agent_fee_payments").select("*").in_("status", ["pending", "paid"]).execute().data or []
    for row in open_rows:
        try:
            if row["status"] == "pending":
                last = row.get("last_checked_at")
                if last and now - _parse_dt(last) < timedelta(minutes=UNPAID_CHECK_EVERY_MIN):
                    continue
            elif row.get("activate_after") and now < _parse_dt(row["activate_after"]):
                continue            # still inside the 30-minute wait
            process_payment(row)
            n += 1
        except Exception as e:
            logger.error("AGENT FEE JOB: error on %s: %s", row.get("reference"), e)
    return n


async def _loop():
    await asyncio.sleep(45)
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception as e:
            logger.error("AGENT FEE JOB: %s", e)
        await asyncio.sleep(LOOP_SECONDS)


_installed = False


def install(app) -> None:
    global _installed
    app.include_router(router)

    async def _start():
        asyncio.create_task(_loop())

    app.on_event("startup")(_start)
    _installed = True
    logger.info("AGENT FEE: mounted at /agent-fee (GH₵%s, activate %s min after payment)", AGENT_FEE, ACTIVATION_DELAY_MIN)
