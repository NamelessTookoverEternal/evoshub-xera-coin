import importlib
import types

import pytest
from eth_account import Account


# ---------------------------------------------------------------- helpers

def _setup(fake, *, reference_id="session-100", amount=1000.0, user_id=1, wallet="verified", chain="BNB"):
    fake.store["xera_chain_config"] = [{
        "chain": "BNB", "network": "testnet", "xera_distributor_address": "0x" + "AB" * 20,
        "xera_vesting_address": "0x" + "CD" * 20, "xera_migration_address": None, "onchain_enabled": True,
    }]
    fake.store["xera_transactions"] = [{
        "id": 987654, "user_id": user_id, "reference_id": reference_id, "type": "MINING_REWARD",
        "status": "CONFIRMED", "amount": amount, "direction": "CREDIT", "created_at": "2026-10-01T00:00:00Z",
    }]
    addr = Account.create().address
    fake.store["xera_external_wallets"] = []
    if wallet == "verified":
        fake.store["xera_external_wallets"].append(
            {"user_id": user_id, "chain": chain, "address": addr, "status": "VERIFIED", "connection_method": "wallet"})
    elif wallet == "manual":
        fake.store["xera_external_wallets"].append(
            {"user_id": user_id, "chain": chain, "address": addr, "status": "PENDING", "connection_method": "manual"})

    reserved = []

    def reserve(p):
        table = fake.store.setdefault("xera_onchain_claims", [])
        if any(r["reference_id"] == p["p_reference_id"] for r in table):
            raise RuntimeError("reference_already_reserved")
        row = {"id": len(table) + 1, "reference_id": p["p_reference_id"], "user_id": p["p_user_id"],
               "chain": p["p_chain"], "wallet_address": p["p_wallet_address"], "claimed_amount": p["p_claimed_amount"],
               "transferable_amount": p["p_transferable_amount"], "locked_amount": p["p_locked_amount"],
               "contract_address": p["p_contract_address"], "status": "SIGNED", "transaction_hash": None}
        table.append(row)
        reserved.append(dict(p))
        return types.SimpleNamespace(data=[row])

    fake.rpc_handlers["xera_reserve_onchain_claim"] = reserve
    return addr, reserved


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", Account.create().key.hex())
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "97")
    monkeypatch.delenv("BNB_CHAIN_ID", raising=False)


def _claims():
    return importlib.import_module("xera.chain.claims")


# ---------------------------------------------------------------- transactions: id vs reference_id

def test_transactions_return_both_id_and_reference_id(fake_supabase, monkeypatch):
    _setup(fake_supabase)
    wallet = importlib.import_module("xera.wallet")
    monkeypatch.setattr(wallet, "supabase", fake_supabase)

    tx = wallet.get_transactions(1)[0]
    assert tx["id"] == 987654                       # kept — other code relies on it
    assert tx["reference_id"] == "session-100"      # what /claim/sign looks entitlements up by
    assert tx["type"] == "MINING_REWARD" and tx["status"] == "CONFIRMED"
    assert tx["onchain_claim_status"] is None


def test_transactions_show_onchain_claim_status_only_for_the_owners_claims(fake_supabase, monkeypatch):
    _setup(fake_supabase)
    fake_supabase.store["xera_onchain_claims"] = [
        {"reference_id": "session-100", "user_id": 1, "status": "CONFIRMED", "chain": "BNB"},
        {"reference_id": "session-100", "user_id": 2, "status": "SIGNED", "chain": "TON"},   # someone else's row
    ]
    wallet = importlib.import_module("xera.wallet")
    monkeypatch.setattr(wallet, "supabase", fake_supabase)
    tx = wallet.get_transactions(1)[0]
    assert (tx["onchain_claim_status"], tx["onchain_claim_chain"]) == ("CONFIRMED", "BNB")


def test_the_original_bug_claiming_with_the_row_id_finds_nothing_but_reference_id_works(fake_supabase):
    _setup(fake_supabase)
    claims = _claims()
    with pytest.raises(claims.ClaimError, match="entitlement_not_found"):
        claims.sign_claim(1, "987654", "BNB")                  # tx.id  -> what the frontend used to send
    assert claims.sign_claim(1, "session-100", "BNB")["chain"] == "BNB"   # tx.reference_id


# ---------------------------------------------------------------- authorization

def test_a_user_cannot_claim_another_users_entitlement(fake_supabase):
    _setup(fake_supabase, user_id=1)
    claims = _claims()
    with pytest.raises(claims.ClaimError, match="entitlement_not_found"):
        claims.sign_claim(2, "session-100", "BNB")
    assert fake_supabase.store.get("xera_onchain_claims", []) == []


# ---------------------------------------------------------------- wallet eligibility

def test_manual_address_can_never_settle_a_claim(fake_supabase):
    _setup(fake_supabase, wallet="manual")
    claims = _claims()
    with pytest.raises(claims.ClaimError, match="wallet_not_verified"):
        claims.sign_claim(1, "session-100", "BNB")
    assert fake_supabase.store.get("xera_onchain_claims", []) == []      # nothing reserved


def test_no_wallet_at_all_is_reported_distinctly(fake_supabase):
    _setup(fake_supabase, wallet="none")
    claims = _claims()
    with pytest.raises(claims.ClaimError, match="no_verified_wallet"):
        claims.sign_claim(1, "session-100", "BNB")


def test_verified_wallet_on_the_wrong_chain_does_not_count(fake_supabase):
    _setup(fake_supabase, wallet="verified", chain="TON")
    claims = _claims()
    with pytest.raises(claims.ClaimError, match="no_verified_wallet"):
        claims.sign_claim(1, "session-100", "BNB")


# ---------------------------------------------------------------- 25 / 75 and signing payload

def test_reservation_records_the_25_75_split_and_signing_payload_matches(fake_supabase):
    addr, reserved = _setup(fake_supabase, amount=1000.0)
    claim = _claims().sign_claim(1, "session-100", "BNB")

    assert len(reserved) == 1
    r = reserved[0]
    assert r["p_claimed_amount"] == 1000.0
    assert r["p_transferable_amount"] == pytest.approx(250.0)
    assert r["p_locked_amount"] == pytest.approx(750.0)
    assert r["p_wallet_address"] == addr

    assert int(claim["transferable_wei"]) == int(claim["amount_wei"]) * 25 // 100
    assert int(claim["transferable_wei"]) + int(claim["locked_wei"]) == int(claim["amount_wei"])
    assert claim["user"] == addr and claim["signature"].startswith("0x") and claim["deadline"] > 0


def test_signing_never_marks_anything_settled_and_records_no_tx_hash(fake_supabase):
    _setup(fake_supabase)
    _claims().sign_claim(1, "session-100", "BNB")
    row = fake_supabase.store["xera_onchain_claims"][0]
    assert row["status"] == "SIGNED" and row["transaction_hash"] is None


@pytest.mark.parametrize("chain_id", [97, 56])
def test_signing_domain_follows_the_configured_chain_id(fake_supabase, monkeypatch, chain_id):
    _setup(fake_supabase)
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", str(chain_id))
    assert _claims().sign_claim(1, "session-100", "BNB")["chain_id"] == chain_id


def test_legacy_bnb_chain_id_env_still_honoured(fake_supabase, monkeypatch):
    _setup(fake_supabase)
    monkeypatch.delenv("XERA_BNB_CHAIN_ID")
    monkeypatch.setenv("BNB_CHAIN_ID", "56")
    assert _claims().sign_claim(1, "session-100", "BNB")["chain_id"] == 56


# ---------------------------------------------------------------- double-claim protection

def test_second_request_while_a_claim_is_in_flight_is_rejected_without_a_second_reservation(fake_supabase):
    _, reserved = _setup(fake_supabase)
    fake_supabase.rpc_handlers["xera_expire_stale_onchain_claims"] = lambda p: types.SimpleNamespace(data=0)  # nothing expired yet
    claims = _claims()
    claims.sign_claim(1, "session-100", "BNB")
    with pytest.raises(claims.ClaimError, match="claim_in_progress"):
        claims.sign_claim(1, "session-100", "BNB")             # double click / second tab
    with pytest.raises(claims.ClaimError, match="claim_in_progress"):
        claims.sign_claim(1, "session-100", "BNB")             # replay
    assert len(reserved) == 1


def test_a_settled_entitlement_cannot_be_claimed_again_on_either_chain(fake_supabase):
    _setup(fake_supabase)
    fake_supabase.store["xera_onchain_claims"] = [
        {"reference_id": "session-100", "user_id": 1, "chain": "BNB", "status": "CONFIRMED"}]
    claims = _claims()
    for chain in ("BNB", "TON"):
        with pytest.raises(claims.ClaimError, match="claim_already_settled"):
            claims.sign_claim(1, "session-100", chain)


def test_the_database_race_guard_is_translated_not_swallowed(fake_supabase):
    """Two requests pass the application pre-check at the same instant; the
    unique index in Postgres is what actually stops the second one."""
    _setup(fake_supabase)
    original = fake_supabase.rpc_handlers["xera_reserve_onchain_claim"]

    def racing(p):
        # another tab wins the race between our pre-check and our INSERT
        fake_supabase.store.setdefault("xera_onchain_claims", []).append(
            {"reference_id": p["p_reference_id"], "user_id": 1, "chain": "BNB", "status": "SIGNED"})
        return original(p)

    fake_supabase.rpc_handlers["xera_reserve_onchain_claim"] = racing
    claims = _claims()
    with pytest.raises(claims.ClaimError, match="already_claimed_or_reserved"):
        claims.sign_claim(1, "session-100", "BNB")
    assert len([r for r in fake_supabase.store["xera_onchain_claims"] if r["reference_id"] == "session-100"]) == 1


# ---------------------------------------------------------------- abandoned signature recovery

def _stale_signed_row(fake, chain="BNB", status="SIGNED"):
    fake.store["xera_onchain_claims"] = [{
        "reference_id": "session-100", "user_id": 1, "chain": chain, "status": status,
        "claimed_amount": 1000.0, "transaction_hash": None}]

    def sweep(_p):
        for r in fake.store["xera_onchain_claims"]:
            if r["status"] == "SIGNED":
                r["status"] = "EXPIRED"            # deadline has passed
        return types.SimpleNamespace(data=1)

    def retry(p):
        row = fake.store["xera_onchain_claims"][0]
        assert row["status"] in ("FAILED", "EXPIRED")
        row.update(status="SIGNED", chain=p["p_chain"], wallet_address=p["p_wallet_address"])
        return types.SimpleNamespace(data=[row])

    fake.rpc_handlers["xera_expire_stale_onchain_claims"] = sweep
    fake.rpc_handlers["xera_retry_onchain_claim"] = retry


def test_rejected_wallet_popup_does_not_strand_the_claim_after_the_signature_expires(fake_supabase):
    _setup(fake_supabase)
    _stale_signed_row(fake_supabase)
    claim = _claims().sign_claim(1, "session-100", "BNB")       # transparently re-signs the SAME row
    assert claim["signature"].startswith("0x")
    rows = fake_supabase.store["xera_onchain_claims"]
    assert len(rows) == 1 and rows[0]["status"] == "SIGNED"      # still exactly one reservation


def test_expired_attempt_on_another_chain_requires_an_explicit_retry(fake_supabase):
    _setup(fake_supabase)
    _stale_signed_row(fake_supabase, chain="TON")
    claims = _claims()
    with pytest.raises(claims.ClaimError, match="claim_on_other_chain"):
        claims.sign_claim(1, "session-100", "BNB")
