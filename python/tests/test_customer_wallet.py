"""Wallet price maths + the 'no cross-buying' guarantees for the customer wallet."""
import sys, types
import pytest
from fastapi import HTTPException

cw = pytest.importorskip("services.evosdata.customer_wallet")


@pytest.fixture(autouse=True)
def fixed_discount(monkeypatch):
    monkeypatch.setattr(cw, "wallet_discount", lambda: 0.10)


def test_wallet_is_ten_pesewas_cheaper():
    assert cw.wallet_price(5.50, 4.0) == 5.40
    assert cw.wallet_price(5.00, 4.0) == 4.90       # XERA-discounted card price -> wallet price


def test_wallet_price_never_below_cost():
    assert cw.wallet_price(4.05, 4.00) == 4.00


def test_uses_its_own_tables_not_agent_wallet():
    src = open(cw.__file__).read()
    assert "agent_wallets" not in src and "agent_transactions" not in src
    assert "customer_wallets" in src and "customer_wallet_purchase" in src


def test_no_withdraw_route():
    paths = {r.path for r in cw.router.routes}
    assert not any("withdraw" in p for p in paths)
