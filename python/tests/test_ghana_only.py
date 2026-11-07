"""
EVOS Data is Ghana-only: every phone / mobile-money number is validated on the
backend (not just in the browser) and normalised to 0XXXXXXXXX.
Run: pytest tests/test_ghana_only.py
"""
import os, sys
sys.path.insert(0, os.getcwd())
for k, v in {"SUPABASE_URL": "https://abc.supabase.co",
             "SUPABASE_SERVICE_ROLE_KEY": "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZSJ9.abc",
             "XERA_TOKEN_SECRET": "y" * 40, "ADMIN_SECRET": "b" * 40}.items():
    os.environ.setdefault(k, v)
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from services.evosdata import core, evoxera_bot

GOOD = [
    ("0551234567", "0551234567"),          # MTN
    ("055 123 4567", "0551234567"),
    ("+233551234567", "0551234567"),
    ("233551234567", "0551234567"),
    ("00233551234567", "0551234567"),
    ("551234567", "0551234567"),
    ("0201234567", "0201234567"),          # Telecel
    ("0501234567", "0501234567"),
    ("0261234567", "0261234567"),          # AirtelTigo
    ("0571234567", "0571234567"),
    ("(024)-123-4567", "0241234567"),
]
BAD = [
    "+2348012345678",      # Nigeria
    "08012345678",         # Nigeria local, 11 digits
    "+14155552671",        # US
    "447911123456",        # UK
    "0301234567",          # Ghana landline-style prefix, not a mobile
    "0991234567",          # not a Ghana mobile prefix
    "055123456",           # too short after the 0
    "05512345678",         # too long
    "abcdefghij",
    "", "0", "+233",
    "٠٥٥١٢٣٤٥٦٧",           # non-ASCII digits
]


@pytest.mark.parametrize("raw,want", GOOD)
def test_ghana_numbers_accepted_and_normalised(raw, want):
    assert core.ghana_phone(raw) == want


@pytest.mark.parametrize("raw", BAD)
def test_non_ghana_numbers_rejected(raw):
    with pytest.raises(ValueError) as e:
        core.ghana_phone(raw)
    assert "Ghana" in str(e.value)


def test_normalise_phone_raises_400():
    assert core.normalise_phone("+233241234567") == "0241234567"
    with pytest.raises(HTTPException) as e:
        core.normalise_phone("+2348012345678")
    assert e.value.status_code == 400 and "Ghana" in e.value.detail


def test_order_request_normalises_and_rejects():
    ok = core.CreateOrderRequest(network="MTN", bundle="1GB", phone="+233 55 123 4567")
    assert ok.phone == "0551234567"
    with pytest.raises(ValidationError):
        core.CreateOrderRequest(network="MTN", bundle="1GB", phone="+2348012345678")


def test_every_model_with_a_phone_field_enforces_ghana():
    cases = [
        (core.RegisterRequest, dict(username="kofi", full_name="Kofi A", email="k@x.com", password="secret1"), "phone"),
        (core.CreateOrderRequest, dict(network="MTN", bundle="1GB"), "phone"),
        (core.VerifyNumberRequest, dict(), "phoneNumber"),
        (core.AgentBuyDataRequest, dict(agent_id=1, network="MTN", bundle="1GB"), "phone_number"),
        (core.StoreOrderRequest, dict(agent_id=1, network="MTN", bundle="1GB"), "phone_number"),
        (core.CheckerStoreOrderRequest, dict(agent_id=1, checker_type="WAEC"), "phone_number"),
        (core.WithdrawRequest, dict(agent_id=1, amount=10, network="MTN"), "mobile_number"),
        (core.VerifyAccountRequest, dict(agent_id=1, network="MTN"), "mobile_number"),
        (core.CreateCheckerOrderRequest, dict(checker_type="WAEC"), "phone_number"),
        (core.AgentBuyCheckerRequest, dict(agent_id=1, checker_type="WAEC"), "phone_number"),
    ]
    for model, base, field in cases:
        good = model(**base, **{field: "233551234567"})
        assert getattr(good, field) == "0551234567", model.__name__
        with pytest.raises(ValidationError):
            model(**base, **{field: "+2348012345678"})


def test_whatsapp_bot_uses_ghana_prefixes():
    assert evoxera_bot.normalise_ghana_phone("0241234567") == "0241234567"
    assert evoxera_bot.normalise_ghana_phone("233551234567") == "0551234567"
    assert evoxera_bot.normalise_ghana_phone("0991234567") is None
    assert evoxera_bot.normalise_ghana_phone("+2348012345678") is None
