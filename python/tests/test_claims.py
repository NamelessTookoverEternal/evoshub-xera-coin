import types
from datetime import datetime, timezone

import pytest
from eth_account import Account


def _seed_chain_config(fake_supabase, distributor="0x" + "AB" * 20, enabled=True, vesting="0x" + "CD" * 20):
    fake_supabase.store["xera_chain_config"] = [{
        "chain": "BNB", "network": "testnet",
        "xera_distributor_address": distributor,
        "xera_vesting_address": vesting,
        "xera_migration_address": None,
        "onchain_enabled": enabled,
    }]


def _seed_mining_tx(fake_supabase, user_id, reference_id, amount):
    fake_supabase.store["xera_transactions"] = [{
        "user_id": user_id, "reference_id": reference_id, "type": "MINING_REWARD",
        "status": "CONFIRMED", "amount": amount,
    }]


def _seed_verified_wallet(fake_supabase, user_id, chain, address):
    fake_supabase.store["xera_external_wallets"] = [{
        "user_id": user_id, "chain": chain, "address": address, "status": "VERIFIED",
    }]


def _install_reserve_rpc(fake_supabase):
    def handler(params):
        table = fake_supabase.store.setdefault("xera_onchain_claims", [])
        if any(r["reference_id"] == params["p_reference_id"] for r in table):
            raise RuntimeError("reference_already_reserved")
        row = {
            "id": len(table) + 1,
            "reference_id": params["p_reference_id"],
            "user_id": params["p_user_id"],
            "chain": params["p_chain"],
            "wallet_address": params["p_wallet_address"],
            "claimed_amount": params["p_claimed_amount"],
            "transferable_amount": params["p_transferable_amount"],
            "locked_amount": params["p_locked_amount"],
            "contract_address": params["p_contract_address"],
            "status": "SIGNED",
        }
        table.append(row)
        return types.SimpleNamespace(data=[row])

    fake_supabase.rpc_handlers["xera_reserve_onchain_claim"] = handler


@pytest.fixture(autouse=True)
def _signer_key(monkeypatch):
    acct = Account.create()
    monkeypatch.setenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", acct.key.hex())
    monkeypatch.setenv("BNB_CHAIN_ID", "97")
    yield acct


def test_sign_claim_produces_a_valid_25_75_split(fake_supabase, _signer_key):
    _install_reserve_rpc(fake_supabase)
    _seed_chain_config(fake_supabase)
    _seed_mining_tx(fake_supabase, user_id=1, reference_id="session-100", amount=1000.0)
    wallet_addr = Account.create().address
    _seed_verified_wallet(fake_supabase, user_id=1, chain="BNB", address=wallet_addr)

    from xera.chain.claims import sign_claim

    result = sign_claim(1, "session-100", "BNB")

    assert result["chain"] == "BNB"
    assert int(result["transferable_wei"]) + int(result["locked_wei"]) == int(result["amount_wei"])
    assert int(result["transferable_wei"]) == int(result["amount_wei"]) * 2500 // 10000
    assert result["signature"].startswith("0x")


def test_sign_claim_rejects_a_reference_id_already_reserved_on_another_chain(fake_supabase, _signer_key):
    _install_reserve_rpc(fake_supabase)
    _seed_chain_config(fake_supabase)
    _seed_mining_tx(fake_supabase, user_id=1, reference_id="session-200", amount=500.0)
    wallet_addr = Account.create().address
    _seed_verified_wallet(fake_supabase, user_id=1, chain="BNB", address=wallet_addr)

    from xera.chain.claims import sign_claim, ClaimError

    sign_claim(1, "session-200", "BNB")  # first reservation succeeds

    with pytest.raises(ClaimError) as exc:
        sign_claim(1, "session-200", "BNB")  # same reference_id again -> must fail
    assert str(exc.value) == "already_claimed_or_reserved"


def test_sign_claim_requires_a_verified_wallet(fake_supabase, _signer_key):
    _install_reserve_rpc(fake_supabase)
    _seed_chain_config(fake_supabase)
    _seed_mining_tx(fake_supabase, user_id=2, reference_id="session-300", amount=10.0)
    # No wallet seeded.

    from xera.chain.claims import sign_claim, ClaimError

    with pytest.raises(ClaimError) as exc:
        sign_claim(2, "session-300", "BNB")
    assert str(exc.value) == "no_verified_wallet"


def test_sign_claim_rejects_unknown_entitlement(fake_supabase, _signer_key):
    _install_reserve_rpc(fake_supabase)
    _seed_chain_config(fake_supabase)

    from xera.chain.claims import sign_claim, ClaimError

    with pytest.raises(ClaimError) as exc:
        sign_claim(3, "nonexistent-session", "BNB")
    assert str(exc.value) == "entitlement_not_found"


def test_sign_claim_respects_onchain_disabled_flag(fake_supabase, _signer_key):
    _install_reserve_rpc(fake_supabase)
    _seed_chain_config(fake_supabase, enabled=False)
    _seed_mining_tx(fake_supabase, user_id=4, reference_id="session-400", amount=10.0)
    _seed_verified_wallet(fake_supabase, user_id=4, chain="BNB", address=Account.create().address)

    from xera.chain.claims import sign_claim, ClaimError

    with pytest.raises(ClaimError) as exc:
        sign_claim(4, "session-400", "BNB")
    assert str(exc.value) == "onchain_disabled"


def test_confirm_claim_rejects_a_claim_that_does_not_belong_to_the_caller(fake_supabase, monkeypatch, _signer_key):
    fake_supabase.store["xera_onchain_claims"] = [{
        "id": 1, "reference_id": "session-500", "user_id": 999, "chain": "BNB",
        "status": "SIGNED", "wallet_address": "0x0", "contract_address": "0x0",
        "claimed_amount": 10.0,
    }]

    from xera.chain.claims import confirm_claim, ClaimError

    with pytest.raises(ClaimError) as exc:
        confirm_claim(1, "session-500", "0xdeadbeef")
    assert str(exc.value) == "not_your_claim"


def test_sign_claim_ton_branch_is_wired_and_produces_a_valid_signature(fake_supabase, monkeypatch):
    """The TON claim-signing blocker (`ton_claim_signing_not_yet_wired`) is
    gone — this exercises the real wiring through claims.sign_claim,
    including the actual Ed25519 signature production via
    ton_claim_signer, not just the signer module in isolation."""
    monkeypatch.setenv("XERA_CLAIM_SIGNER_TON_SEED", "11" * 32)
    _install_reserve_rpc(fake_supabase)
    _seed_chain_config(fake_supabase)
    fake_supabase.store["xera_chain_config"][0]["chain"] = "TON"
    fake_supabase.store["xera_chain_config"][0]["xera_distributor_address"] = "EQ" + "A" * 46
    _seed_mining_tx(fake_supabase, user_id=5, reference_id="session-ton-1", amount=1000.0)
    _seed_verified_wallet(fake_supabase, user_id=5, chain="TON", address="0:" + "22" * 32)

    from xera.chain.claims import sign_claim

    result = sign_claim(5, "session-ton-1", "TON")

    assert result["chain"] == "TON"
    assert result["signature"].startswith("0x")
    assert len(bytes.fromhex(result["signature"][2:])) == 64
    assert int(result["transferable_wei"]) + int(result["locked_wei"]) == int(result["amount_wei"])


def test_sign_claim_maps_global_allocation_exceeded_to_a_claim_error(fake_supabase, _signer_key):
    def handler(params):
        raise RuntimeError("global_mining_allocation_exceeded")

    fake_supabase.rpc_handlers["xera_reserve_onchain_claim"] = handler
    _seed_chain_config(fake_supabase)
    _seed_mining_tx(fake_supabase, user_id=6, reference_id="session-600", amount=10.0)
    _seed_verified_wallet(fake_supabase, user_id=6, chain="BNB", address=Account.create().address)

    from xera.chain.claims import sign_claim, ClaimError

    with pytest.raises(ClaimError) as exc:
        sign_claim(6, "session-600", "BNB")
    assert str(exc.value) == "global_mining_allocation_exceeded"


def test_retry_claim_rejects_a_claim_that_is_not_failed_or_expired(fake_supabase):
    fake_supabase.store["xera_onchain_claims"] = [{
        "id": 1, "reference_id": "session-700", "user_id": 7, "chain": "BNB", "status": "SIGNED",
        "claimed_amount": 10.0,
    }]

    from xera.chain.claims import retry_claim, ClaimError

    with pytest.raises(ClaimError) as exc:
        retry_claim(7, "session-700", "BNB")
    assert str(exc.value) == "claim_not_retryable"
