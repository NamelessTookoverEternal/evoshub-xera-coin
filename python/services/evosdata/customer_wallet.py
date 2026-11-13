"""
Customer wallet for EVOS Data (deposit-only) + paying a data order from it.

Mounted with the other EVOS Data modules (see routes/evosdata.py). Endpoints (X-User-Token required):
    GET  /wallet/me?user_id=                       balance, recent activity, whether this user is an agent
    GET  /wallet/quote?user_id=&network=&bundle=   "is my balance enough?" with and without the XERA discount
    POST /wallet/deposit/initiate   {user_id, amount}   Paystack top-up (the fee is worked out HERE, not in the browser)
    POST /wallet/deposit/verify     {reference}         confirm a top-up and credit it once

Paying an order from the wallet is `POST /orders/create` with pay_with="wallet" (core.create_order calls pay_order()).

Rules (agreed with the owner):
  * Every customer has a wallet (customer_wallets). Agents have one too, SEPARATE from their agent wallet:
    no transfers either way, so customer funds can never buy at agent base price.
  * Customers can only ADD money and SPEND it. There is no withdrawal.
  * Paying from the wallet takes a flat discount (customer_wallet_settings.discount_ghs, default 0.10) off the amount
    the order would cost on Paystack (XERA-discounted or not), but never below the bundle's cost price.
  * Checkout tries the wallet first (with or without the XERA discount). If the balance is not enough, nothing is
    taken and the customer is told so and can top up or pay with Paystack as before.
  * The money and the order are created in ONE database transaction (wallet_purchase), so a crash can never take
    money without an order. A wallet order that fails is refunded automatically by a database trigger.
"""
from __future__ import annotations

import importlib
import logging
import sys
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from utils.rate_limit import limiter

logger = logging.getLogger("customer_wallet")

router = APIRouter(prefix="/wallet", tags=["wallet"])

MIN_TOPUP = 1.0
MAX_TOPUP = 5000.0
DUPLICATE_WINDOW_SECONDS = 90          # same wallet order twice within this window is treated as a double tap

_MAIN = "services.evosdata.core"


def _m():
    mod = sys.modules.get(_MAIN)
    return mod if mod is not None else importlib.import_module(_MAIN)


def _db():
    return _m().supabase


def _money(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _balance(user_id: int) -> float:
    rows = _db().table("customer_wallets").select("balance").eq("user_id", user_id).limit(1).execute().data or []
    return float(rows[0]["balance"] or 0) if rows else 0.0


def _is_agent(user_id: int) -> bool:
    rows = _db().table("users").select("role, agent_status").eq("id", user_id).limit(1).execute().data or []
    return bool(rows and rows[0].get("role") == "agent" and rows[0].get("agent_status") == "approved")


def _label(tx: dict) -> str:
    ref = str(tx.get("reference") or "")
    if ref.startswith("refund:"):
        return "Refund"
    if ref.startswith("EVOS-CDP-"):
        return "Top-up"
    if ref.startswith("EVOS-WLT-"):
        return "Data purchase"
    return (tx.get("note") or ("Money in" if tx.get("type") == "credit" else "Money out"))[:60]


def _price_row(network: str, bundle: str):
    rows = _db().table("prices").select("price, cost_price").eq("network", network).eq("bundle", bundle).limit(1).execute().data or []
    if not rows:
        raise HTTPException(400, "Invalid bundle")
    return float(rows[0]["price"]), float(rows[0].get("cost_price") or 0)


def wallet_discount() -> float:
    try:
        rows = _db().table("customer_wallet_settings").select("discount_ghs").eq("id", 1).limit(1).execute().data or []
        return float(rows[0]["discount_ghs"]) if rows else 0.10
    except Exception:
        return 0.10


def wallet_price(card_price: float, cost_price: float) -> float:
    """Wallet price = what Paystack would charge minus the wallet discount, never below cost price."""
    return float(max(_money(card_price - wallet_discount()), _money(cost_price or 0), Decimal("0.01")))


# ------------------------------------------------------------------ read

@router.get("/me")
@limiter.limit("60/minute")
def wallet_me(request: Request, user_id: int):
    m = _m()
    m.require_user(request, user_id)
    txs = _db().table("customer_wallet_transactions").select("type, amount, reference, note, created_at") \
        .eq("user_id", user_id).order("id", desc=True).limit(12).execute().data or []
    agent = _is_agent(user_id)
    return {
        "status": "ok",
        "balance": _balance(user_id),
        "is_agent": agent,
        "can_withdraw": agent,                      # customers: deposit-only
        "transactions": [{"type": t.get("type"), "amount": float(t.get("amount") or 0), "label": _label(t),
                          "created_at": t.get("created_at")} for t in txs],
    }


@router.get("/quote")
@limiter.limit("60/minute")
def wallet_quote(request: Request, user_id: int, network: str, bundle: str):
    """The 'scan': can the wallet pay for this bundle, at full price and (if switched on and eligible) with XERA?"""
    m = _m()
    m.require_user(request, user_id)
    price, cost = _price_row(network, bundle)
    balance = _balance(user_id)
    wprice = wallet_price(price, cost)
    out = {
        "status": "ok", "balance": balance, "price": price, "wallet_price": wprice, "wallet_discount": round(price - wprice, 2),
        "enough": balance + 1e-9 >= wprice, "shortfall": round(max(wprice - balance, 0), 2),
        "xera": None, "discounted_price": None, "wallet_price_with_xera": None,
        "enough_with_xera": None, "shortfall_with_xera": None,
    }
    try:
        q = m.xera_discount.quote(_db(), user_id, price)
        if q.get("enabled") and q.get("eligible"):
            final = float(q["final_price"])
            wfinal = wallet_price(final, cost)
            out.update(xera=m.xera_discount.public_quote(q), discounted_price=final, wallet_price_with_xera=wfinal,
                       enough_with_xera=balance + 1e-9 >= wfinal, shortfall_with_xera=round(max(wfinal - balance, 0), 2))
    except Exception as exc:                       # the discount is optional: the full-price answer still stands
        logger.warning("wallet quote: XERA quote unavailable: %s", exc)
    return out


# ------------------------------------------------------------------ top-up

class TopUpRequest(BaseModel):
    user_id: int
    amount: float = Field(ge=MIN_TOPUP, le=MAX_TOPUP)


@router.post("/deposit/initiate")
@limiter.limit("10/minute")
def deposit_initiate(request: Request, payload: TopUpRequest):
    m = _m()
    m.require_user(request, payload.user_id)
    amount = float(_money(payload.amount))
    fee = 0.0                                       # top-ups carry no extra fee: you load X, the wallet gets X
    total = amount

    users = _db().table("users").select("email").eq("id", payload.user_id).limit(1).execute().data or []
    if not users:
        raise HTTPException(404, "User not found")
    reference = f"EVOS-CDP-{payload.user_id}-{uuid.uuid4().hex[:10].upper()}"
    try:
        res = requests.post(
            "https://api.paystack.co/transaction/initialize",
            headers={"Authorization": f"Bearer {m.PAYSTACK_SECRET}", "Content-Type": "application/json"},
            json={
                "email": users[0].get("email") or "guest@evoshub.com", "amount": int(round(total * 100)),
                "reference": reference, "currency": "GHS",
                "metadata": {"user_id": payload.user_id, "type": "wallet_deposit", "credit_amount": amount},
                "callback_url": f"{m.callback_base(request)}/success?type=deposit",
            }, timeout=m.REQUEST_TIMEOUT,
        ).json()
    except requests.exceptions.RequestException:
        raise HTTPException(502, "Payment service error. Please try again.")
    if not res.get("status"):
        raise HTTPException(400, res.get("message") or "Could not start the payment")

    _db().table("customer_wallet_deposits").insert({
        "user_id": payload.user_id, "reference": reference, "amount": amount, "total_charge": total, "status": "pending",
    }).execute()
    return {"status": "created", "reference": reference, "credit": amount, "fee": fee, "total": total,
            "payment_url": res["data"]["authorization_url"]}


class VerifyRequest(BaseModel):
    reference: str = Field(min_length=6, max_length=80)


@router.post("/deposit/verify")
@limiter.limit("30/minute")
def deposit_verify(request: Request, payload: VerifyRequest):
    m = _m()
    db = _db()
    ref = payload.reference.strip()
    rows = db.table("customer_wallet_deposits").select("*").eq("reference", ref).limit(1).execute().data or []
    if not rows:
        raise HTTPException(404, "Deposit not found")
    dep = rows[0]
    user_id = int(dep["user_id"])
    m.require_user(request, user_id)                # only the owner of the deposit can confirm it

    if dep.get("status") == "credited":
        return {"status": "already_credited", "balance": _balance(user_id)}

    try:
        res = requests.get(f"https://api.paystack.co/transaction/verify/{dep['reference']}",
                           headers={"Authorization": f"Bearer {m.PAYSTACK_SECRET}"}, timeout=m.REQUEST_TIMEOUT).json()
    except requests.exceptions.RequestException:
        raise HTTPException(502, "Could not reach the payment service. Try again in a moment.")
    pay = res.get("data") or {}
    if not res.get("status") or pay.get("status") != "success":
        return {"status": "pending", "balance": _balance(user_id)}          # not paid (yet): never marked failed here

    expected = int(round(float(dep.get("total_charge") or dep["amount"]) * 100))
    if int(pay.get("amount") or 0) < expected - 1 or str(pay.get("currency") or "GHS").upper() != "GHS":
        logger.error("wallet deposit %s: paid %s, expected %s - NOT credited", dep.get("id"), pay.get("amount"), expected)
        raise HTTPException(400, "The payment amount does not match this top-up. Please contact support.")

    # Atomic claim, exactly like the agent flow: only the caller that flips the status proceeds.
    claim = db.table("customer_wallet_deposits").update({"status": "credited"}).eq("id", dep["id"]).neq("status", "credited").execute()
    if not claim.data:
        return {"status": "already_credited", "balance": _balance(user_id)}
    try:
        db.rpc("customer_wallet_credit", {"p_user_id": user_id, "p_amount": str(_money(dep["amount"])), "p_reference": dep["reference"],
                                 "p_note": "Wallet top-up via Paystack"}).execute()
    except Exception as exc:
        db.table("customer_wallet_deposits").update({"status": "pending"}).eq("id", dep["id"]).execute()   # let a retry credit it
        logger.error("wallet deposit %s: credit failed: %s", dep.get("id"), exc)
        raise HTTPException(502, "Your payment is safe but the credit did not finish. Please try again in a minute.")
    return {"status": "credited", "credited": float(dep["amount"]), "balance": _balance(user_id)}


# ------------------------------------------------------------------ pay an order from the wallet

def pay_order(request: Request, data) -> dict:
    """Called by core.create_order when pay_with == 'wallet'. `data.user_id` is already proven by the user token."""
    m = _m()
    db = _db()
    user_id = data.user_id
    if not user_id:
        raise HTTPException(403, "Sign in to pay from your wallet.")

    price, cost = _price_row(data.network, data.bundle)
    phone = data.phone

    # Double-tap guard: the same wallet order for the same number moments ago.
    since = (m.utc_now() - timedelta(seconds=DUPLICATE_WINDOW_SECONDS)).isoformat()
    dup = db.table("orders").select("id").eq("user_id", user_id).eq("network", data.network).eq("bundle", data.bundle) \
        .eq("phone_number", phone).like("paystack_ref", "EVOS-WLT-%").gte("created_at", since).limit(1).execute().data
    if dup:
        raise HTTPException(409, "You just placed this exact order. Check your orders before buying it again.")

    reference = f"EVOS-WLT-{user_id}-{uuid.uuid4().hex[:10].upper()}"
    card_price = price                              # what Paystack would charge (before the wallet discount)
    held = False
    discount_info = None
    if data.use_xera:
        q = m.xera_discount.quote(db, user_id, price)
        if not q["eligible"]:
            raise HTTPException(400, q["message"] or "The XERA discount is not available right now.")
        try:
            m.xera_discount.place_hold(db, user_id, reference, q)
        except m.xera_discount.DiscountError as de:
            raise HTTPException(400, de.message)
        held = True
        card_price = float(q["final_price"])
        discount_info = m.xera_discount.public_quote(q)

    charge = wallet_price(card_price, cost)
    balance = _balance(user_id)
    if balance + 1e-9 < charge:
        if held:
            m.xera_discount.release(db, reference)
        raise HTTPException(402, detail={"code": "insufficient_wallet", "balance": balance, "needed": charge,
                                         "shortfall": round(charge - balance, 2),
                                         "message": f"Your wallet has GH₵{balance:.2f} but this order needs GH₵{charge:.2f}."})

    try:
        res = db.rpc("customer_wallet_purchase", {"p_user_id": user_id, "p_price": str(_money(charge)), "p_reference": reference,
                                         "p_network": data.network, "p_bundle": data.bundle, "p_phone": phone}).execute()
        out = res.data if isinstance(res.data, dict) else (res.data[0] if res.data else {})
    except Exception as exc:
        if held:
            m.xera_discount.release(db, reference)
        if "insufficient_balance" in str(exc):          # the balance changed between the check and the purchase
            raise HTTPException(402, detail={"code": "insufficient_wallet", "balance": _balance(user_id), "needed": charge,
                                             "shortfall": round(charge - _balance(user_id), 2),
                                             "message": "Your wallet balance changed. Please check and try again."})
        logger.error("wallet purchase failed for user %s: %s", user_id, exc)
        raise HTTPException(500, "Could not complete the purchase. Nothing was taken from your wallet.")

    if held:
        m.xera_discount.consume(db, reference)          # the order is paid: take the held XERA (never raises)
    try:
        m.increment_user_orders(user_id)
    except Exception:
        logger.warning("wallet purchase: could not bump order count for user %s", user_id)

    order = (db.table("orders").select("*").eq("paystack_ref", reference).limit(1).execute().data or [{}])[0]
    result = m.dispatch_paid_order(order, reference)
    if result.get("status") != "success":
        # dispatch_paid_order marked the order failed; the database trigger has already returned the money (and XERA).
        raise HTTPException(502, detail={"code": "delivery_failed", "balance": _balance(user_id), "reference": reference,
                                         "message": "We could not send this bundle to the network right now. Your money is back in your wallet."})

    resp = {"status": True, "paid_with": "wallet", "reference": reference, "order_id": out.get("order_id"),
            "new_wallet_balance": _balance(user_id), "charged": charge,
            "message": f"{data.bundle} {data.network} is on its way to {phone}."}
    if discount_info:
        resp["xera_discount"] = discount_info
    return resp


def install(app) -> None:
    app.include_router(router)
    logger.info("CUSTOMER WALLET: mounted at /wallet")
