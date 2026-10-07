"""
Amount-based on-chain claims: input validation, the exact 25/75 split, the
reservation call, failure handling, the HTTP routes, and the daily-claim pool
errors. The balance/pool ARITHMETIC lives in Postgres
(supabase/migrations/20261006_xera_amount_claims.sql) and was exercised against a
real database; here the reservation RPC is a faithful stand-in so the Python
layer around it can be tested end to end with REAL signing and REAL tokens.
"""
import importlib
import types
from decimal import Decimal

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data  # noqa: F401  (import check only)
from fastapi import FastAPI
from fastapi.testclient import TestClient

DIST = "0x" + "AB" * 20


def _claims():
    return importlib.import_module("xera.chain.claims")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", Account.create().key.hex())
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "97")
    monkeypatch.setenv("XERA_TOKEN_SECRET", "test-secret")
    monkeypatch.delenv("BNB_CHAIN_ID", raising=False)
    monkeypatch.delenv("XERA_MIN_ONCHAIN_CLAIM", raising=False)


def _setup(fake, *, claimable=100.0, wallet="verified", chain="BNB", user_id=1):
    fake.store["xera_chain_config"] = [{
        "chain": "BNB", "network": "testnet", "xera_distributor_address": DIST,
        "xera_vesting_address": "0x" + "CD" * 20, "xera_migration_address": None, "onchain_enabled": True,
    }]
    addr = Account.create().address
    fake.store["xera_external_wallets"] = []
    if wallet == "verified":
        fake.store["xera_external_wallets"].append(
            {"user_id": user_id, "chain": chain, "address": addr, "status": "VERIFIED", "connection_method": "wallet"})
    elif wallet == "manual":
        fake.store["xera_external_wallets"].append(
            {"user_id": user_id, "chain": chain, "address": addr, "status": "PENDING", "connection_method": "manual"})

    state = {"claimable": Decimal(str(claimable)), "reserved": [], "failed": []}

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

    def mark_failed(p):
        state["failed"].append(p["p_reference_id"])
        return types.SimpleNamespace(data=[{}])

    fake.rpc_handlers["xera_reserve_onchain_claim_amount"] = reserve
    fake.rpc_handlers["xera_mark_onchain_claim_failed"] = mark_failed
    fake.rpc_handlers["xera_claimable_balance"] = lambda p: types.SimpleNamespace(data=[{
        "cached_balance": float(state["claimable"]) + 50, "eligible_total": 200, "onchain_total": 0,
        "claimable": float(state["claimable"])}])
    return addr, state


# ------------------------------------------------------------ input validation

@pytest.mark.parametrize("raw", ["1", "10", "10.5", "10.50", "0.01".replace("0.01", "1.00"), "75000000", 12, "  7  "])
def test_valid_amounts_are_accepted(fake_supabase, raw):
    assert _claims().parse_claim_amount(raw) > 0


@pytest.mark.parametrize("raw", ["", "abc", "-5", "+5", "0", "0.00", "1e3", "1E+3", "NaN", "Infinity", "1,000", "1 000",
                                 "5.", ".5", "١٢٣", "1_000", None, True, "76000000000"])
def test_garbage_amounts_are_rejected(fake_supabase, raw):
    with pytest.raises(_claims().ClaimError) as e:
        _claims().parse_claim_amount(raw)
    assert str(e.value) in ("invalid_amount", "amount_below_minimum")


def test_more_than_two_decimals_is_its_own_error(fake_supabase):
    with pytest.raises(_claims().ClaimError, match="amount_too_precise"):
        _claims().parse_claim_amount("1.234")


def test_dust_below_the_minimum_is_rejected_and_the_minimum_is_configurable(fake_supabase, monkeypatch):
    c = _claims()
    with pytest.raises(c.ClaimError, match="amount_below_minimum"):
        c.parse_claim_amount("0.50")
    monkeypatch.setenv("XERA_MIN_ONCHAIN_CLAIM", "25")
    with pytest.raises(c.ClaimError, match="amount_below_minimum"):
        c.parse_claim_amount("24.99")
    assert c.parse_claim_amount("25") == Decimal("25")


@pytest.mark.parametrize("amount", ["1", "3.13", "99.99", "1234.56", "7.77", "0.01".replace("0.01", "1.01")])
def test_the_25_75_split_is_exact_for_every_two_decimal_amount(fake_supabase, amount):
    c = _claims()
    a = c.parse_claim_amount(amount)
    transferable, locked = c.split_claim_amount(a)
    assert transferable + locked == a                                   # nothing lost or invented
    assert transferable == a * Decimal("0.25")
    # and it fits NUMERIC(20,4) without rounding, which the DB's CHECK requires
    assert transferable == transferable.quantize(Decimal("0.0001"))
    assert locked == locked.quantize(Decimal("0.0001"))
    wei = c._decimal_to_wei(a)
    assert wei == int(a * 10**18)
    assert (wei * 2500) // 10000 + (wei - (wei * 2500) // 10000) == wei


# ------------------------------------------------------------ signing flow

def test_sign_amount_claim_reserves_exactly_the_requested_amount_and_signs_it(fake_supabase):
    addr, state = _setup(fake_supabase, claimable=100)
    claim = _claims().sign_amount_claim(1, "BNB", "40")

    assert len(state["reserved"]) == 1
    r = state["reserved"][0]
    assert r["p_amount"] == "40" and Decimal(r["p_transferable_amount"]) == Decimal("10") and Decimal(r["p_locked_amount"]) == Decimal("30")
    assert r["p_wallet_address"] == addr and r["p_reference_id"].startswith("claim-")

    assert claim["reference_id"] == r["p_reference_id"]
    assert int(claim["amount_wei"]) == 40 * 10**18
    assert int(claim["transferable_wei"]) == 10 * 10**18 and int(claim["locked_wei"]) == 30 * 10**18
    assert claim["user"] == addr and claim["signature"].startswith("0x") and claim["contract_address"] == DIST
    assert state["claimable"] == Decimal("60")


def test_every_claim_gets_its_own_reference_id(fake_supabase):
    _, state = _setup(fake_supabase, claimable=100)
    c = _claims()
    c.sign_amount_claim(1, "BNB", "10")
    c.sign_amount_claim(1, "BNB", "10")
    refs = {r["p_reference_id"] for r in state["reserved"]}
    assert len(refs) == 2


def test_claiming_more_than_the_claimable_balance_is_refused_and_nothing_is_signed(fake_supabase):
    _, state = _setup(fake_supabase, claimable=30)
    with pytest.raises(_claims().ClaimError, match="insufficient_claimable_balance"):
        _claims().sign_amount_claim(1, "BNB", "30.01")
    assert state["reserved"] == [] and state["claimable"] == Decimal("30")


def test_invalid_amount_never_reaches_the_database(fake_supabase):
    _, state = _setup(fake_supabase)
    for bad in ("0", "-1", "1e3", "abc", "1.234"):
        with pytest.raises(_claims().ClaimError):
            _claims().sign_amount_claim(1, "BNB", bad)
    assert state["reserved"] == []


def test_manual_address_can_never_receive_an_amount_claim(fake_supabase):
    _, state = _setup(fake_supabase, wallet="manual")
    with pytest.raises(_claims().ClaimError, match="wallet_not_verified"):
        _claims().sign_amount_claim(1, "BNB", "10")
    assert state["reserved"] == []


def test_no_wallet_is_reported_distinctly(fake_supabase):
    _, state = _setup(fake_supabase, wallet="none")
    with pytest.raises(_claims().ClaimError, match="no_verified_wallet"):
        _claims().sign_amount_claim(1, "BNB", "10")
    assert state["reserved"] == []


def test_onchain_disabled_blocks_before_any_reservation(fake_supabase):
    _, state = _setup(fake_supabase)
    fake_supabase.store["xera_chain_config"][0]["onchain_enabled"] = False
    with pytest.raises(_claims().ClaimError, match="onchain_disabled"):
        _claims().sign_amount_claim(1, "BNB", "10")
    assert state["reserved"] == []


def test_if_signing_fails_after_reserving_the_claim_is_released_for_retry(fake_supabase, monkeypatch):
    _, state = _setup(fake_supabase)
    c = _claims()
    monkeypatch.setattr(c.eip712_signer, "sign_bnb_claim", lambda **_: (_ for _ in ()).throw(RuntimeError("no key")))
    with pytest.raises(c.ClaimError, match="claim_signer_not_configured"):
        c.sign_amount_claim(1, "BNB", "10")
    assert state["failed"] == [state["reserved"][0]["p_reference_id"]]   # marked FAILED at once, not left in limbo


def test_global_allocation_error_is_translated(fake_supabase):
    _setup(fake_supabase)
    def boom(_p):
        raise RuntimeError("global_mining_allocation_exceeded")
    fake_supabase.rpc_handlers["xera_reserve_onchain_claim_amount"] = boom
    with pytest.raises(_claims().ClaimError, match="global_mining_allocation_exceeded"):
        _claims().sign_amount_claim(1, "BNB", "10")


# ------------------------------------------------------------ HTTP routes

@pytest.fixture
def api(fake_supabase):
    routes_chain = importlib.import_module("xera.routes_chain")
    user_auth = importlib.import_module("xera.user_auth")
    app = FastAPI()
    app.include_router(routes_chain.router, prefix="/api/xera")
    return types.SimpleNamespace(
        client=TestClient(app), fake=fake_supabase,
        h=lambda uid: {"Authorization": f"Bearer {user_auth.make_user_token(uid)}"},
    )


def test_amount_claim_routes_require_a_session(api):
    assert api.client.post("/api/xera/claim/sign-amount", json={"chain": "BNB", "amount": "5"}).status_code == 401
    assert api.client.get("/api/xera/claim/overview").status_code == 401


def test_sign_amount_route_happy_path_and_error_mapping(api):
    addr, state = _setup(api.fake, claimable=50)
    ok = api.client.post("/api/xera/claim/sign-amount", headers=api.h(1), json={"chain": "BNB", "amount": "20"})
    assert ok.status_code == 200 and ok.json()["claim"]["reference_id"].startswith("claim-")

    too_much = api.client.post("/api/xera/claim/sign-amount", headers=api.h(1), json={"chain": "BNB", "amount": "31"})
    assert too_much.status_code == 409 and "claimable balance" in too_much.json()["detail"]

    bad = api.client.post("/api/xera/claim/sign-amount", headers=api.h(1), json={"chain": "BNB", "amount": "1e3"})
    assert bad.status_code == 400
    precise = api.client.post("/api/xera/claim/sign-amount", headers=api.h(1), json={"chain": "BNB", "amount": "1.234"})
    assert precise.status_code == 400 and "2 decimal" in precise.json()["detail"]
    small = api.client.post("/api/xera/claim/sign-amount", headers=api.h(1), json={"chain": "BNB", "amount": "0.5"})
    assert small.status_code == 400 and "minimum" in small.json()["detail"]


def test_a_user_cannot_claim_against_someone_elses_wallet(api):
    _setup(api.fake, claimable=50, user_id=1)                 # wallet belongs to user 1 only
    r = api.client.post("/api/xera/claim/sign-amount", headers=api.h(2), json={"chain": "BNB", "amount": "5"})
    assert r.status_code == 400 and "wallet" in r.json()["detail"].lower()


def test_the_old_per_entitlement_sign_route_is_closed(api):
    r = api.client.post("/api/xera/claim/sign", headers=api.h(1), json={"reference_id": "session-1", "chain": "BNB"})
    assert r.status_code == 410
    assert api.client.post("/api/xera/claim/sign", json={}).status_code == 401


def test_overview_reports_balance_and_only_the_callers_claims(api):
    _setup(api.fake, claimable=80)
    api.fake.store["xera_onchain_claims"] = [
        {"reference_id": "claim-mine", "user_id": 1, "chain": "BNB", "claimed_amount": 20, "status": "FAILED", "created_at": "2026-10-06"},
        {"reference_id": "claim-theirs", "user_id": 2, "chain": "BNB", "claimed_amount": 99, "status": "SIGNED", "created_at": "2026-10-06"},
    ]
    r = api.client.get("/api/xera/claim/overview", headers=api.h(1))
    body = r.json()
    assert r.status_code == 200 and body["claimable"] == 80 and body["transferable_percent"] == 25 and body["locked_percent"] == 75
    assert body["min_amount"] == 1
    assert [c["reference_id"] for c in body["claims"]] == ["claim-mine"]


# ------------------------------------------------------------ daily claim pool errors

@pytest.mark.parametrize("code", ["free_mining_closed", "allocation_exhausted"])
def test_daily_claim_surfaces_pool_errors_as_clean_codes(fake_supabase, monkeypatch, code):
    daily = importlib.import_module("xera.daily")
    monkeypatch.setattr(daily, "supabase", fake_supabase)
    monkeypatch.setattr(daily, "get_or_create_wallet", lambda uid: {})
    fake_supabase.store["xera_daily_config"] = [{"id": 1, "enabled": True, "reward_amount": 5}]
    def rpc(_p):
        raise RuntimeError(code)
    fake_supabase.rpc_handlers["xera_claim_daily_reward"] = rpc
    with pytest.raises(daily.DailyClaimError, match=code):
        daily.claim_daily(1)


# ------------------------------------------------------------ abandoned claims become retryable

def test_overview_sweeps_abandoned_claims_so_they_can_be_retried(api):
    _setup(api.fake, claimable=10)
    swept = []
    api.fake.rpc_handlers["xera_expire_stale_onchain_claims"] = lambda p: swept.append(1) or types.SimpleNamespace(data=0)
    assert api.client.get("/api/xera/claim/overview", headers=api.h(1)).status_code == 200
    assert swept == [1]


def test_retry_of_an_abandoned_claim_sweeps_first_then_resigns_the_same_reference(fake_supabase):
    addr, _state = _setup(fake_supabase)
    row = {"id": 1, "reference_id": "claim-old", "user_id": 1, "chain": "BNB", "wallet_address": addr,
           "claimed_amount": 40.0, "transferable_amount": 10.0, "locked_amount": 30.0, "status": "SIGNED"}
    fake_supabase.store["xera_onchain_claims"] = [row]
    fake_supabase.rpc_handlers["xera_expire_stale_onchain_claims"] = lambda p: row.update(status="EXPIRED") or types.SimpleNamespace(data=1)
    retried = []
    fake_supabase.rpc_handlers["xera_retry_onchain_claim"] = lambda p: retried.append(p) or types.SimpleNamespace(data=[row])

    claim = _claims().retry_claim(1, "claim-old", "BNB")

    assert retried and retried[0]["p_reference_id"] == "claim-old"        # the SAME reference — never a new one
    assert int(claim["amount_wei"]) == 40 * 10**18 and claim["signature"].startswith("0x")


def test_a_claim_that_is_still_valid_is_not_retryable(fake_supabase):
    addr, _ = _setup(fake_supabase)
    row = {"id": 1, "reference_id": "claim-live", "user_id": 1, "chain": "BNB", "wallet_address": addr,
           "claimed_amount": 5.0, "transferable_amount": 1.25, "locked_amount": 3.75, "status": "SIGNED"}
    fake_supabase.store["xera_onchain_claims"] = [row]
    fake_supabase.rpc_handlers["xera_expire_stale_onchain_claims"] = lambda p: types.SimpleNamespace(data=0)   # deadline not reached
    with pytest.raises(_claims().ClaimError, match="claim_not_retryable"):
        _claims().retry_claim(1, "claim-live", "BNB")
