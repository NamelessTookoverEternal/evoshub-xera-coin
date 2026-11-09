"""
XERA discount on EVOS Data bundles. Run: pytest tests/test_xera_discount.py

Covers the maths, the eligibility rules, and the create_order / webhook wiring against a small
in-memory fake. The Postgres functions themselves (hold / consume / release) are SQL and are NOT
exercised here - see the notes in XERA_DATA_DISCOUNT.md.
"""
import os, sys, types
sys.path.insert(0, os.getcwd())
for k, v in {"SUPABASE_URL": "https://abc.supabase.co",
             "SUPABASE_SERVICE_ROLE_KEY": "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZSJ9.abc",
             "XERA_TOKEN_SECRET": "y" * 40, "ADMIN_SECRET": "b" * 40}.items():
    os.environ.setdefault(k, v)
from decimal import Decimal
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from services.evosdata import core, datamart_stock, xera_discount as xd


# ---------------------------------------------------------------- fake database
class Res:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class Q:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.patch, self.row = db, name, [], None, None

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.filters.append((k, v)); return self
    def limit(self, _n): return self
    def order(self, *_a, **_k): return self
    def insert(self, row): self.row = dict(row); return self
    def update(self, patch): self.patch = dict(patch); return self

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.row is not None:
            self.db.tables[self.name].append(self.row)
            return Res([self.row])
        hit = [r for r in rows if all(r.get(k) == v for k, v in self.filters)]
        if self.patch is not None:
            for r in hit:
                r.update(self.patch)
        return Res(hit)


class FakeDB:
    def __init__(self):
        self.tables = {}
        self.calls = []
        self.spendable = Decimal("100")
        self.hold_error = None

    def table(self, name): return Q(self, name)

    def rpc(self, name, params):
        self.calls.append((name, params))
        if name == "xera_discount_spendable":
            return Res(float(self.spendable))
        if name == "xera_discount_hold":
            if self.hold_error:
                raise RuntimeError(self.hold_error)
            return Res([{"id": 1}])
        if name == "xera_discount_consume":
            return Res([{"id": 1, "status": "CONSUMED", "late": False, "shortfall": 0}])
        return Res(None)


def cfg_row(**over):
    row = {"id": 1, "enabled": True, "xera_per_ghs": 100, "discount_pct": 4, "max_pct": 10,
           "hold_minutes": 30, "require_kyc": True}
    row.update(over)
    return row


def make_db(**over):
    db = FakeDB()
    db.tables["xera_discount_config"] = [cfg_row(**over)]
    db.tables["xera_kyc"] = [{"user_id": 42, "status": "VERIFIED"}]
    return db


# ---------------------------------------------------------------- maths
def test_one_gb_example_five_cedis_pays_four_eighty_for_twenty_xera():
    c = xd.compute(5.00, {"discount_pct": Decimal(4), "max_pct": Decimal(10), "xera_per_ghs": Decimal(100)})
    assert c["discount_ghs"] == Decimal("0.20")
    assert c["xera_amount"] == Decimal("20.0000")
    assert c["final_price"] == Decimal("4.80")
    assert c["final_pesewas"] == 480


def test_pct_can_never_exceed_the_cap():
    c = xd.compute(10, {"discount_pct": Decimal(50), "max_pct": Decimal(10), "xera_per_ghs": Decimal(100)})
    assert c["discount_ghs"] == Decimal("1.00")          # 10% of 10, not 50%


def test_no_discount_when_pct_zero_or_price_zero():
    cfg = {"discount_pct": Decimal(0), "max_pct": Decimal(10), "xera_per_ghs": Decimal(100)}
    assert xd.compute(5, cfg)["discount_ghs"] == 0
    cfg["discount_pct"] = Decimal(4)
    assert xd.compute(0, cfg)["discount_ghs"] == 0


def test_pesewas_are_exact_not_float_truncated():
    c = xd.compute(4.35, {"discount_pct": Decimal(0), "max_pct": Decimal(10), "xera_per_ghs": Decimal(100)})
    assert c["final_pesewas"] == 435                       # int(4.35*100) would give 434


# ---------------------------------------------------------------- quote / eligibility
def test_disabled_is_never_eligible():
    db = make_db(enabled=False)
    q = xd.quote(db, 42, 5.0)
    assert q["enabled"] is False and q["eligible"] is False and q["reason"] == "disabled"


def test_missing_config_table_means_off():
    db = FakeDB()                                          # no config row at all
    assert xd.quote(db, 42, 5.0)["enabled"] is False


def test_guest_gets_sign_in_message():
    q = xd.quote(make_db(), None, 5.0)
    assert q["reason"] == "not_signed_in" and not q["eligible"]


def test_unverified_user_can_still_have_the_discount_for_35_xera():
    db = make_db()
    db.tables["xera_kyc"] = [{"user_id": 42, "status": "PENDING"}]
    q = xd.quote(db, 42, 5.0)
    assert q["eligible"] and q["verified"] is False
    assert q["xera_amount"] == 35.0 and q["xera_if_verified"] == 20.0
    assert q["discount_ghs"] == 0.2 and q["final_price"] == 4.8        # same cash discount
    assert q["_calc"]["xera_amount"] == Decimal("35.0000")             # the hold uses 35, not 20


def test_verified_user_still_pays_20():
    q = xd.quote(make_db(), 42, 5.0)
    assert q["verified"] is True and q["xera_amount"] == 20.0


def test_no_kyc_record_at_all_counts_as_unverified():
    db = make_db()
    db.tables["xera_kyc"] = []
    q = xd.quote(db, 42, 5.0)
    assert q["eligible"] and q["xera_amount"] == 35.0


def test_bigger_bundles_scale_for_both_kinds_of_user():
    db = make_db()
    assert xd.quote(db, 42, 10.0)["xera_amount"] == 40.0
    db.tables["xera_kyc"] = []
    assert xd.quote(db, 42, 10.0)["xera_amount"] == 70.0


def test_multiplier_zero_means_kyc_required_again():
    db = make_db(unverified_multiplier=0)
    db.tables["xera_kyc"] = []
    q = xd.quote(db, 42, 5.0)
    assert q["reason"] == "kyc_required" and not q["eligible"]


def test_unverified_short_balance_asks_for_the_35_amount():
    db = make_db()
    db.tables["xera_kyc"] = []
    db.spendable = Decimal("30")
    q = xd.quote(db, 42, 5.0)
    assert not q["eligible"] and q["xera_short"] == 5.0 and "Earn 5 more XERA" in q["message"]


def test_not_enough_xera_shows_full_price_and_how_much_more():
    db = make_db()
    db.spendable = Decimal("15")
    q = xd.quote(db, 42, 5.0)
    assert not q["eligible"] and q["reason"] == "insufficient_xera"
    assert q["xera_short"] == 5.0 and "Earn 5 more XERA" in q["message"]


def test_enough_xera_is_eligible_and_internal_fields_are_hidden():
    db = make_db()
    q = xd.quote(db, 42, 5.0)
    assert q["eligible"] and q["final_price"] == 4.8 and q["xera_amount"] == 20.0
    assert "_calc" not in xd.public_quote(q)


# ---------------------------------------------------------------- hold / consume
def test_hold_maps_insufficient_balance_to_a_friendly_error():
    db = make_db()
    db.hold_error = "insufficient_balance"
    q = xd.quote(db, 42, 5.0)
    with pytest.raises(xd.DiscountError) as e:
        xd.place_hold(db, 42, "EVD-1", q)
    assert e.value.code == "insufficient_xera"


def test_consume_never_raises():
    class Boom(FakeDB):
        def rpc(self, *_a, **_k): raise RuntimeError("db down")
    assert xd.consume(Boom(), "EVD-1") is None
    assert xd.consume(FakeDB(), None) is None


def test_release_never_raises():
    class Boom(FakeDB):
        def rpc(self, *_a, **_k): raise RuntimeError("db down")
    xd.release(Boom(), "EVD-1")


# ---------------------------------------------------------------- create_order wiring
def req(user_id=None):
    headers = [(b"x-user-token", core.make_user_token(user_id).encode())] if user_id else []
    return Request({"type": "http", "headers": headers, "method": "POST", "path": "/", "client": ("1.1.1.1", 1)})


class PaystackStub:
    def __init__(self, ok=True):
        self.bodies, self.ok = [], ok

    def post(self, url, headers=None, json=None, timeout=None):
        self.bodies.append(json)
        ref = json.get("reference") or "PSK_GENERATED"
        data = {"status": self.ok, "data": {"authorization_url": "https://pay/x", "reference": ref}}
        return types.SimpleNamespace(json=lambda: data)


@pytest.fixture
def shop(monkeypatch):
    db = make_db()
    db.tables["prices"] = [{"network": "MTN", "bundle": "1GB", "price": 5.0}]
    db.tables["users"] = [{"id": 42, "email": "a@b.com"}]
    db.tables["orders"] = []
    monkeypatch.setattr(core, "supabase", db)
    monkeypatch.setattr(datamart_stock, "bundle_in_stock", lambda n, b: True)
    ps = PaystackStub()
    monkeypatch.setattr(core.requests, "post", ps.post)
    return db, ps


def order(use_xera, user=42):
    return core.CreateOrderRequest(user_id=user, network="MTN", bundle="1GB", phone="0241234567", use_xera=use_xera)


def call_create(data, user=42):
    fn = getattr(core.create_order, "__wrapped__", core.create_order)
    return fn(req(user), data)


def test_without_the_toggle_the_price_is_unchanged(shop):
    db, ps = shop
    out = call_create(order(False))
    assert ps.bodies[0]["amount"] == 500 and "reference" not in ps.bodies[0]
    assert db.tables["orders"][0]["price"] == 5.0
    assert not [c for c in db.calls if c[0] == "xera_discount_hold"]
    assert "xera_discount" not in out


def test_unverified_buyer_is_held_for_35_at_checkout(shop):
    db, ps = shop
    db.tables["xera_kyc"] = []
    call_create(order(True))
    hold = [c for c in db.calls if c[0] == "xera_discount_hold"][0][1]
    assert hold["p_xera"] == "35.0000" and hold["p_discount_ghs"] == "0.20" and ps.bodies[0]["amount"] == 480


def test_with_the_toggle_paystack_is_charged_the_discounted_amount_and_xera_is_held(shop):
    db, ps = shop
    out = call_create(order(True))
    assert ps.bodies[0]["amount"] == 480
    ref = ps.bodies[0]["reference"]
    assert ref.startswith("EVD-")
    assert db.tables["orders"][0]["price"] == 4.8 and db.tables["orders"][0]["paystack_ref"] == ref
    hold = [c for c in db.calls if c[0] == "xera_discount_hold"][0][1]
    assert hold["p_order_ref"] == ref and hold["p_xera"] == "20.0000" and hold["p_discount_ghs"] == "0.20"
    assert out["xera_discount"]["final_price"] == 4.8


def test_a_client_cannot_name_its_own_price(shop):
    db, ps = shop
    assert "price" not in core.CreateOrderRequest.__fields__ and "discount" not in core.CreateOrderRequest.__fields__


def test_toggle_with_not_enough_xera_is_refused_not_silently_full_price(shop):
    db, ps = shop
    db.spendable = Decimal("3")
    with pytest.raises(HTTPException) as e:
        call_create(order(True))
    assert e.value.status_code == 400 and "XERA" in e.value.detail
    assert not ps.bodies and not db.tables["orders"]


def test_guest_cannot_use_the_toggle(shop):
    db, ps = shop
    with pytest.raises(HTTPException) as e:
        call_create(order(True, user=None), user=None)
    assert e.value.status_code == 400 and not ps.bodies


def test_feature_off_blocks_the_toggle(shop):
    db, ps = shop
    db.tables["xera_discount_config"][0]["enabled"] = False
    with pytest.raises(HTTPException):
        call_create(order(True))
    assert not ps.bodies


def test_hold_is_released_if_paystack_fails(shop, monkeypatch):
    db, ps = shop
    ps.ok = False
    with pytest.raises(HTTPException):
        call_create(order(True))
    names = [c[0] for c in db.calls]
    assert "xera_discount_hold" in names and "xera_discount_release" in names
    assert not db.tables["orders"]


def test_hold_is_kept_once_the_order_exists(shop):
    db, ps = shop
    call_create(order(True))
    assert "xera_discount_release" not in [c[0] for c in db.calls]


def test_quote_endpoint_returns_disabled_when_off(shop):
    db, ps = shop
    db.tables["xera_discount_config"][0]["enabled"] = False
    fn = getattr(core.xera_discount_quote, "__wrapped__", core.xera_discount_quote)
    assert fn(req(42), network="MTN", bundle="1GB", user_id=42) == {"enabled": False}


def test_quote_endpoint_needs_the_users_token(shop):
    db, ps = shop
    fn = getattr(core.xera_discount_quote, "__wrapped__", core.xera_discount_quote)
    with pytest.raises(HTTPException) as e:
        fn(req(None), network="MTN", bundle="1GB", user_id=42)
    assert e.value.status_code == 403


def test_quote_endpoint_returns_the_deal(shop):
    db, ps = shop
    fn = getattr(core.xera_discount_quote, "__wrapped__", core.xera_discount_quote)
    out = fn(req(42), network="MTN", bundle="1GB", user_id=42)
    assert out["eligible"] and out["final_price"] == 4.8 and out["xera_amount"] == 20.0
