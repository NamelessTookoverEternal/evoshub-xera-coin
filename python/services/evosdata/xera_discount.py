"""
XERA discount on EVOS Data bundles.

A signed-in, KYC-verified user can spend a little in-app XERA for a small
promotional discount on a data bundle. Everything is decided on the server:
the browser only sends "use_xera: true" and is told the result.

Lifecycle of one discounted order (all money moves are Postgres functions, see
supabase/migrations/20261107_xera_data_discount_v1.sql):

    quote()       read-only: what would the discount be, can this user have it?
    place_hold()  payment is about to start: the XERA is HELD (cannot be spent twice)
    consume()     Paystack confirmed: the hold becomes a real ledger debit (idempotent)
    release()     the buyer never paid: the hold is freed

It is OFF until xera_discount_config.enabled = true. If anything about the
discount fails, the normal full-price order is never affected.

The discount is a promotional discount set by EVOS. It is not a price for
XERA and does not give XERA a monetary value.
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from typing import Any, Optional

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
XERA_UNIT = Decimal("0.0001")

DEFAULT_CONFIG = {
    "enabled": False,
    "xera_per_ghs": Decimal("100"),
    "discount_pct": Decimal("4"),
    "max_pct": Decimal("10"),
    "hold_minutes": 30,
    "require_kyc": True,          # legacy column, no longer used: see unverified_multiplier
    "unverified_multiplier": Decimal("1.75"),   # unverified users pay 1.75x the XERA (20 -> 35). 0 = KYC required
}


class DiscountError(Exception):
    """A reason the discount cannot be applied. `code` is stable, `message` is user-facing."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _dec(v: Any, default: Decimal) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return default


def load_config(sb) -> dict:
    """Settings row, or the safe 'disabled' defaults if the table is missing / unreachable."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        res = sb.table("xera_discount_config").select("*").eq("id", 1).limit(1).execute()
        row = (res.data or [None])[0]
        if row:
            cfg["enabled"] = bool(row.get("enabled"))
            cfg["xera_per_ghs"] = _dec(row.get("xera_per_ghs"), DEFAULT_CONFIG["xera_per_ghs"])
            cfg["discount_pct"] = _dec(row.get("discount_pct"), DEFAULT_CONFIG["discount_pct"])
            cfg["max_pct"] = _dec(row.get("max_pct"), DEFAULT_CONFIG["max_pct"])
            cfg["hold_minutes"] = int(row.get("hold_minutes") or DEFAULT_CONFIG["hold_minutes"])
            cfg["require_kyc"] = bool(row.get("require_kyc", True))
            if row.get("unverified_multiplier") is not None:
                cfg["unverified_multiplier"] = _dec(row.get("unverified_multiplier"),
                                                    DEFAULT_CONFIG["unverified_multiplier"])
    except Exception as exc:  # table not migrated yet, or a transient error -> feature stays off
        logger.warning("XERA DISCOUNT: config unavailable (%s) - treating as disabled", exc)
        cfg["enabled"] = False
    return cfg


def compute(price: Any, cfg: dict) -> dict:
    """Pure maths. price 5.00 at 4% / 100 XERA per GHS -> discount 0.20, 20 XERA, pay 4.80."""
    price_d = _dec(price, Decimal("0")).quantize(CENT, ROUND_HALF_UP)
    pct = min(cfg["discount_pct"], cfg["max_pct"])
    discount = (price_d * pct / Decimal("100")).quantize(CENT, ROUND_HALF_UP)
    hard_cap = (price_d * cfg["max_pct"] / Decimal("100")).quantize(CENT, ROUND_DOWN)
    discount = min(discount, hard_cap)
    if price_d <= 0 or discount <= 0 or discount >= price_d:
        discount = Decimal("0.00")
    xera = (discount * cfg["xera_per_ghs"]).quantize(XERA_UNIT, ROUND_HALF_UP)
    final = price_d - discount
    return {
        "list_price": price_d,
        "discount_ghs": discount,
        "xera_amount": xera,
        "final_price": final,
        "final_pesewas": int((final * 100).to_integral_value(ROUND_HALF_UP)),
    }


def _scalar(res) -> Decimal:
    data = getattr(res, "data", res)
    if isinstance(data, list):
        data = data[0] if data else 0
    if isinstance(data, dict):
        data = next(iter(data.values()), 0)
    return _dec(data, Decimal("0"))


def _kyc_verified(sb, user_id: int) -> bool:
    res = sb.table("xera_kyc").select("status").eq("user_id", user_id).limit(1).execute()
    row = (res.data or [None])[0]
    return bool(row and row.get("status") == "VERIFIED")


def quote(sb, user_id: Optional[int], price: Any, cfg: Optional[dict] = None) -> dict:
    """
    What the user would get. Never raises for 'not eligible': returns eligible=False plus a
    reason and message so the page can show the normal price with a short note.
    """
    cfg = cfg or load_config(sb)
    calc = compute(price, cfg)
    out = {
        "enabled": bool(cfg["enabled"]),
        "eligible": False,
        "reason": "",
        "message": "",
        "list_price": float(calc["list_price"]),
        "discount_ghs": float(calc["discount_ghs"]),
        "xera_amount": float(calc["xera_amount"]),
        "final_price": float(calc["final_price"]),
        "final_pesewas": calc["final_pesewas"],
        "xera_per_ghs": float(cfg["xera_per_ghs"]),
        "spendable": 0.0,
        "xera_short": 0.0,
        "verified": False,
        "xera_if_verified": float(calc["xera_amount"]),
        "hold_minutes": cfg["hold_minutes"],
        "_calc": calc,
    }
    if not cfg["enabled"]:
        out.update(reason="disabled", message="The XERA discount is not available right now.")
        return out
    if not user_id:
        out.update(reason="not_signed_in", message="Sign in to use your XERA discount.")
        return out
    if calc["discount_ghs"] <= 0:
        out.update(reason="no_discount", message="No XERA discount on this bundle.")
        return out
    try:
        verified = _kyc_verified(sb, user_id)
        if not verified:
            mult = cfg["unverified_multiplier"]
            if mult <= 0:
                out.update(reason="kyc_required",
                           message="Verify your identity in the XERA app to use your XERA discount.")
                return out
            # Same cash discount, more XERA for accounts that have not done KYC.
            calc = dict(calc)
            calc["xera_amount"] = (calc["xera_amount"] * mult).quantize(XERA_UNIT, ROUND_HALF_UP)
            out["_calc"] = calc
            out["xera_amount"] = float(calc["xera_amount"])
        out["verified"] = bool(verified)
        spendable = _scalar(sb.rpc("xera_discount_spendable", {"p_user_id": int(user_id)}).execute())
    except Exception as exc:
        logger.warning("XERA DISCOUNT: quote lookup failed for user %s: %s", user_id, exc)
        out.update(reason="unavailable", message="The XERA discount is unavailable right now.")
        return out

    out["spendable"] = float(spendable)
    if spendable < calc["xera_amount"]:
        short = (calc["xera_amount"] - spendable).quantize(XERA_UNIT)
        out.update(reason="insufficient_xera", xera_short=float(short),
                   message=f"Earn {short.normalize():f} more XERA to get GH₵ {calc['discount_ghs']} off.")
        return out
    out.update(eligible=True, reason="ok", message="")
    return out


def public_quote(q: dict) -> dict:
    """Quote without internal fields, safe to return to the browser."""
    return {k: v for k, v in q.items() if not k.startswith("_")}


def place_hold(sb, user_id: int, order_ref: str, q: dict, cfg: Optional[dict] = None) -> None:
    """Hold the XERA for this order. Raises DiscountError if the balance is no longer enough."""
    cfg = cfg or load_config(sb)
    calc = q["_calc"]
    try:
        sb.rpc("xera_discount_hold", {
            "p_user_id": int(user_id),
            "p_order_ref": order_ref,
            "p_xera": str(calc["xera_amount"]),
            "p_discount_ghs": str(calc["discount_ghs"]),
            "p_minutes": int(cfg["hold_minutes"]),
        }).execute()
    except Exception as exc:
        text = str(exc)
        if "insufficient_balance" in text:
            raise DiscountError("insufficient_xera",
                                "Your XERA balance changed. Please check the price again.")
        if "wallet_not_found" in text or "wallet_not_active" in text:
            raise DiscountError("wallet_unavailable", "Your XERA wallet is not available for a discount.")
        logger.error("XERA DISCOUNT: hold failed for user %s ref %s: %s", user_id, order_ref, exc)
        raise DiscountError("unavailable", "The XERA discount is unavailable right now.")


def consume(sb, order_ref: Optional[str]) -> Optional[dict]:
    """
    Payment confirmed -> turn the hold into the real debit. Idempotent, and it never raises:
    the customer has paid, so a problem here must not stop the order being fulfilled.
    """
    if not order_ref:
        return None
    try:
        res = sb.rpc("xera_discount_consume", {"p_order_ref": order_ref}).execute()
        data = getattr(res, "data", None)
        row = data[0] if isinstance(data, list) and data else data
        if isinstance(row, dict) and row.get("id") is None:
            return None  # composite NULL: this order had no XERA discount
        if isinstance(row, dict) and (row.get("late") or float(row.get("shortfall") or 0) > 0):
            logger.warning("XERA DISCOUNT: ref %s honoured with late=%s shortfall=%s",
                           order_ref, row.get("late"), row.get("shortfall"))
        return row if isinstance(row, dict) else None
    except Exception as exc:
        logger.error("XERA DISCOUNT: consume failed for ref %s: %s", order_ref, exc)
        return None


def release(sb, order_ref: Optional[str]) -> None:
    """The order will not be paid: free the held XERA. Never raises."""
    if not order_ref:
        return
    try:
        sb.rpc("xera_discount_release", {"p_order_ref": order_ref}).execute()
    except Exception as exc:
        logger.error("XERA DISCOUNT: release failed for ref %s: %s", order_ref, exc)
