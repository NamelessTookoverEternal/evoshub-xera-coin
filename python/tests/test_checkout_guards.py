"""
Checkout guards: out-of-stock blocks the order before any payment, and a
client-supplied user_id is only a claim. Run: pytest tests/test_checkout_guards.py
"""
import os, sys
sys.path.insert(0, os.getcwd())
for k, v in {"SUPABASE_URL": "https://abc.supabase.co",
             "SUPABASE_SERVICE_ROLE_KEY": "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZSJ9.abc",
             "XERA_TOKEN_SECRET": "y" * 40, "ADMIN_SECRET": "b" * 40}.items():
    os.environ.setdefault(k, v)
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from services.evosdata import core, datamart_stock


def req(token=None):
    headers = [(b"x-user-token", token.encode())] if token else []
    return Request({"type": "http", "headers": headers, "method": "POST", "path": "/"})


def test_no_claim_is_guest():
    assert core.resolve_order_identity(req(), None) is None


def test_claim_without_token_is_guest_order():
    assert core.resolve_order_identity(req(), 42) is None


def test_valid_token_attaches_order():
    assert core.resolve_order_identity(req(core.make_user_token(42)), 42) == 42


def test_token_for_other_user_refused():
    with pytest.raises(HTTPException) as e:
        core.resolve_order_identity(req(core.make_user_token(7)), 42)
    assert e.value.status_code == 403


def test_garbage_token_refused():
    with pytest.raises(HTTPException) as e:
        core.resolve_order_identity(req("junk.junk"), 42)
    assert e.value.status_code == 403


def test_out_of_stock_order_blocked_before_payment(monkeypatch):
    monkeypatch.setattr(datamart_stock, "bundle_in_stock", lambda n, b: False)
    touched = []
    monkeypatch.setattr(core.supabase, "table", lambda *a, **k: touched.append(a) or (_ for _ in ()).throw(AssertionError("DB touched")))
    data = core.CreateOrderRequest(network="MTN", bundle="50GB", phone="0241234567")
    with pytest.raises(HTTPException) as e:
        core.create_order.__wrapped__(req(), data) if hasattr(core.create_order, "__wrapped__") else core.create_order(req(), data)
    assert e.value.status_code == 400
    assert "out of stock" in e.value.detail.lower()
    assert not touched
