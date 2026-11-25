"""
Withdrawing to a manually added (typed) BNB address.

Rules under test:
  * a manual address can receive a withdrawal ONLY with the account password, AND after its waiting period;
  * a wrong / missing password reserves nothing;
  * repeated wrong passwords are throttled;
  * a connected (signature-verified) wallet behaves exactly as before, no password asked;
  * TON manual addresses never settle;
  * the signed claim is for the typed address, and the amount is reserved exactly once.
"""
import datetime
import importlib
import types
from decimal import Decimal

import pytest
from eth_account import Account
from fastapi import FastAPI
from fastapi.testclient import TestClient

DIST = "0x" + "AB" * 20
PASSWORD = "right-pass"


@pytest.fixture(autouse=True)
def _ready_users(fake_supabase):
    from conftest import mark_transfer_ready
    mark_transfer_ready(fake_supabase)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", Account.create().key.hex())
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "97")
    monkeypatch.setenv("XERA_TOKEN_SECRET", "test-secret")
    monkeypatch.delenv("BNB_CHAIN_ID", raising=False)
    monkeypatch.delenv("XERA_MIN_ONCHAIN_CLAIM", raising=False)
    monkeypatch.delenv("XERA_MANUAL_WALLET_COOLDOWN_SECONDS", raising=False)


def _iso(hours_ago):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)).isoformat()


def _setup(fake, *, wallet="manual", added_hours_ago=13, chain="BNB", claimable=100.0, user_id=1):
    from xera.chain.wallet_link import manual_cooldown_seconds  # noqa: F401  (import check)
    fake.store["xera_chain_config"] = [{
        "chain": "BNB", "network": "testnet", "xera_distributor_address": DIST,
        "xera_vesting_address": "0x" + "CD" * 20, "xera_migration_address": None, "onchain_enabled": True}]
    from xera.routes_auth import pwd_context
    fake.store["users"] = [{"id": user_id, "password": pwd_context.hash(PASSWORD)}]
    addr = Account.create().address
    fake.store["xera_external_wallets"] = []
    if wallet == "manual":
        fake.store["xera_external_wallets"].append(
            {"user_id": user_id, "chain": chain, "address": addr, "status": "PENDING",
             "connection_method": "manual", "linked_at": _iso(added_hours_ago)})
    elif wallet == "verified":
        fake.store["xera_external_wallets"].append(
            {"user_id": user_id, "chain": chain, "address": addr, "status": "VERIFIED",
             "connection_method": "wallet", "verified_at": _iso(50), "linked_at": _iso(50)})

    state = {"claimable": Decimal(str(claimable)), "reserved": []}

    def reserve(p):
        amount = Decimal(p["p_amount"])
        if amount > state["claimable"]:
            raise RuntimeError("insufficient_claimable_balance")
        state["claimable"] -= amount
        row = {"id": len(state["reserved"]) + 1, "reference_id": p["p_reference_id"], "user_id": p["p_user_id"],
               "chain": p["p_chain"], "wallet_address": p["p_wallet_address"], "claimed_amount": float(amount),
               "transferable_amount": float(Decimal(p["p_transferable_amount"])),
               "locked_amount": float(Decimal(p["p_locked_amount"])), "status": "SIGNED"}
        fake.store.setdefault("xera_onchain_claims", []).append(row)
        state["reserved"].append(dict(p))
        return types.SimpleNamespace(data=[row])

    fake.rpc_handlers["xera_reserve_onchain_claim_amount"] = reserve
    fake.rpc_handlers["xera_mark_onchain_claim_failed"] = lambda p: types.SimpleNamespace(data=[{}])
    return addr, state


@pytest.fixture
def api(fake_supabase):
    routes_chain = importlib.import_module("xera.routes_chain")
    routes_chain._pw_failures.clear()
    user_auth = importlib.import_module("xera.user_auth")
    app = FastAPI()
    app.include_router(routes_chain.router, prefix="/api/xera")
    return types.SimpleNamespace(
        client=TestClient(app), fake=fake_supabase,
        h=lambda uid: {"Authorization": f"Bearer {user_auth.make_user_token(uid)}"},
    )


def _sign(api, **body):
    return api.client.post("/api/xera/claim/sign-amount", headers=api.h(1), json={"chain": "BNB", "amount": "10", **body})


# ------------------------------------------------------------ happy path

def test_manual_address_with_password_after_cooldown_is_signed_for_the_typed_address(api):
    addr, state = _setup(api.fake)
    r = _sign(api, password=PASSWORD)
    assert r.status_code == 200, r.text
    claim = r.json()["claim"]
    assert claim["user"].lower() == addr.lower()
    assert len(state["reserved"]) == 1
    assert state["reserved"][0]["p_wallet_address"].lower() == addr.lower()


# ------------------------------------------------------------ password

def test_missing_password_reserves_nothing(api):
    _, state = _setup(api.fake)
    r = _sign(api)
    assert r.status_code == 400 and "password" in r.json()["detail"].lower()
    assert state["reserved"] == []


def test_wrong_password_reserves_nothing(api):
    _, state = _setup(api.fake)
    r = _sign(api, password="nope")
    assert r.status_code == 403 and "not correct" in r.json()["detail"]
    assert state["reserved"] == []


def test_repeated_wrong_passwords_are_throttled_even_if_the_next_one_is_right(api):
    _, state = _setup(api.fake)
    for _ in range(5):
        assert _sign(api, password="nope").status_code == 403
    r = _sign(api, password=PASSWORD)
    assert r.status_code == 429
    assert state["reserved"] == []


def test_right_password_clears_the_failure_counter(api):
    _, state = _setup(api.fake)
    for _ in range(3):
        _sign(api, password="nope")
    assert _sign(api, password=PASSWORD).status_code == 200
    for _ in range(3):
        assert _sign(api, password="nope").status_code == 403   # counter restarted, not throttled


# ------------------------------------------------------------ cooldown

def test_new_manual_address_cannot_be_withdrawn_to_during_the_cooldown(api):
    _, state = _setup(api.fake, added_hours_ago=2)
    r = _sign(api, password=PASSWORD)
    assert r.status_code == 403 and "waiting period" in r.json()["detail"]
    assert state["reserved"] == []


def test_cooldown_ends_exactly_at_the_configured_time(api, monkeypatch):
    _, state = _setup(api.fake, added_hours_ago=2)
    monkeypatch.setenv("XERA_MANUAL_WALLET_COOLDOWN_SECONDS", str(60 * 60))   # 1h instead of 12h
    assert _sign(api, password=PASSWORD).status_code == 200


def test_unreadable_timestamp_fails_closed(api):
    _, state = _setup(api.fake)
    api.fake.store["xera_external_wallets"][0]["linked_at"] = "now"
    assert _sign(api, password=PASSWORD).status_code == 403
    assert state["reserved"] == []


def test_wallet_list_tells_the_page_when_the_address_becomes_usable(api):
    _setup(api.fake, added_hours_ago=2)
    r = api.client.get("/api/xera/wallet/linked", headers=api.h(1))
    w = r.json()["wallets"][0]
    ready = datetime.datetime.fromisoformat(w["withdraw_ready_at"])
    hours_left = (ready - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 3600
    assert 9.9 < hours_left < 10.1


# ------------------------------------------------------------ unchanged paths

def test_verified_wallet_needs_no_password_and_ignores_one(api):
    addr, state = _setup(api.fake, wallet="verified")
    assert _sign(api).status_code == 200
    assert len(state["reserved"]) == 1


def test_no_wallet_at_all_still_reports_no_wallet(api):
    _, state = _setup(api.fake, wallet="none")
    r = _sign(api, password=PASSWORD)
    assert r.status_code == 400 and "must be connected" in r.json()["detail"]
    assert state["reserved"] == []


def test_ton_manual_address_never_settles(api):
    _, state = _setup(api.fake, chain="TON")
    r = api.client.post("/api/xera/claim/sign-amount", headers=api.h(1),
                        json={"chain": "TON", "amount": "10", "password": PASSWORD})
    assert r.status_code == 400
    assert state["reserved"] == []


def test_claim_code_alone_still_refuses_a_manual_address_without_the_opt_in(fake_supabase):
    """The route is the only caller that opts in, after the password. Any other caller stays safe by default."""
    _, state = _setup(fake_supabase)
    claims = importlib.import_module("xera.chain.claims")
    with pytest.raises(claims.ClaimError, match="wallet_not_verified"):
        claims.sign_amount_claim(1, "BNB", "10")
    assert state["reserved"] == []


# ------------------------------------------------------------ retry

def test_retry_to_a_manual_address_also_needs_the_password(api):
    addr, state = _setup(api.fake)
    api.fake.store["xera_onchain_claims"] = [{
        "reference_id": "claim-1", "user_id": 1, "chain": "BNB", "status": "FAILED",
        "claimed_amount": 10.0, "network": "testnet", "wallet_address": addr}]
    api.fake.rpc_handlers["xera_retry_onchain_claim"] = lambda p: types.SimpleNamespace(data=[{}])
    no_pw = api.client.post("/api/xera/claim/retry", headers=api.h(1), json={"reference_id": "claim-1", "chain": "BNB"})
    assert no_pw.status_code == 400
    ok = api.client.post("/api/xera/claim/retry", headers=api.h(1),
                         json={"reference_id": "claim-1", "chain": "BNB", "password": PASSWORD})
    assert ok.status_code == 200, ok.text
    assert ok.json()["claim"]["user"].lower() == addr.lower()


# ------------------------------------------------------------ one address, one account

def test_address_held_by_another_account_is_refused_with_a_clear_message(api):
    def taken(_p):
        raise RuntimeError("address_already_linked")
    api.fake.rpc_handlers["xera_set_manual_wallet"] = taken
    r = api.client.post("/api/xera/wallet/manual", headers=api.h(1),
                        json={"chain": "BNB", "address": Account.create().address})
    assert r.status_code == 409 and "another account" in r.json()["detail"]
