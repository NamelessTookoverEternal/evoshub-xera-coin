"""
Mainnet-readiness fixes (audit blockers C1, C2, C5, C6):

  C1  exact Decimal wei conversion — signing and confirming must agree on every amount
  C2  claims are stamped testnet/mainnet; a claim never crosses networks
  C5  the verifier refuses a wrong-chain RPC and a not-yet-final transaction
  C6  a transaction that is merely pending must not release the reservation
"""
import importlib
import types
from decimal import Decimal

import pytest
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_utils import keccak

DIST = "0x" + "AB" * 20


def _mark_transfer_ready(fake):
    # Load tests/conftest.py by path: several conftest.py files exist, so `from conftest import ...`
    # can resolve to the wrong one depending on collection order.
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location("xera_root_conftest", pathlib.Path(__file__).with_name("conftest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.mark_transfer_ready(fake)


def _claims():
    return importlib.import_module("xera.chain.claims")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", Account.create().key.hex())
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "97")
    monkeypatch.setenv("XERA_TOKEN_SECRET", "test-secret")
    monkeypatch.delenv("BNB_CHAIN_ID", raising=False)
    monkeypatch.delenv("XERA_TON_NETWORK", raising=False)
    monkeypatch.delenv("XERA_BNB_CONFIRMATIONS", raising=False)
    monkeypatch.delenv("XERA_MIN_ONCHAIN_CLAIM", raising=False)


# ------------------------------------------------------------------ C1: exact wei

# float(x) * 1e18 is NOT x * 10**18 for these (found by running the old code).
@pytest.mark.parametrize("amount", ["0.07", "1.15", "4.6", "33.3", "12.35", "100.10", "75000000"])
def test_wei_conversion_is_exact_for_every_amount(fake_supabase, amount):
    c = _claims()
    expected = int(Decimal(amount) * 10**18)
    assert c._to_wei(amount) == expected
    assert c._to_wei(Decimal(amount)) == expected
    assert c._to_wei(float(amount)) == expected      # what Postgres/JSON hands back for a NUMERIC column
    assert c._decimal_to_wei(Decimal(amount)) == expected


def test_old_float_conversion_really_was_wrong(fake_supabase):
    """Guards the guard: proves these amounts used to disagree, so the test above is meaningful."""
    wrong = [a for a in ("0.07", "1.15", "4.6", "33.3")
             if int(round(float(a) * 10**18)) != int(Decimal(a) * 10**18)]
    assert wrong


# ------------------------------------------------------------------ shared stub

def _prepare(fake, *, network="testnet", status="SIGNED", amount=1.15):
    fake.store["xera_chain_config"] = [{
        "chain": "BNB", "network": network, "xera_distributor_address": DIST,
        "xera_vesting_address": "0x" + "CD" * 20, "xera_migration_address": None, "onchain_enabled": True,
    }]
    fake.store["xera_onchain_claims"] = [{
        "id": 1, "reference_id": "claim-x", "user_id": 1, "chain": "BNB", "wallet_address": Account.create().address,
        "claimed_amount": amount, "transferable_amount": amount / 4, "locked_amount": amount * 0.75,
        "contract_address": DIST, "status": status, "network": network,
    }]
    calls = {"failed": [], "confirmed": [], "retried": []}
    fake.rpc_handlers["xera_mark_onchain_claim_failed"] = lambda p: (calls["failed"].append(p), types.SimpleNamespace(data=[{}]))[1]
    fake.rpc_handlers["xera_confirm_onchain_claim"] = lambda p: (calls["confirmed"].append(p), types.SimpleNamespace(data=[{"status": "CONFIRMED"}]))[1]
    fake.rpc_handlers["xera_retry_onchain_claim"] = lambda p: (calls["retried"].append(p), types.SimpleNamespace(data=[{}]))[1]
    return calls


def test_confirm_checks_the_same_wei_that_was_signed(fake_supabase, monkeypatch):
    c = _claims()
    _prepare(fake_supabase, amount=1.15)
    seen = {}

    def fake_verify(**kw):
        seen.update(kw)
        return {"block_number": 7, "transferable": 0, "locked": 0}

    monkeypatch.setattr(c, "verify_bnb_claim_tx", fake_verify)
    c.confirm_claim(1, "claim-x", "0x" + "11" * 32)
    assert seen["expected_total_amount_wei"] == c._decimal_to_wei(Decimal("1.15")) == 1_150_000_000_000_000_000


# ------------------------------------------------------------------ C2: networks

def test_onchain_network_follows_the_configured_chain(fake_supabase, monkeypatch):
    from xera.chain.config import onchain_network
    assert onchain_network("BNB") == "testnet"
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "56")
    assert onchain_network("BNB") == "mainnet"
    assert onchain_network("TON") == "testnet"
    monkeypatch.setenv("XERA_TON_NETWORK", "mainnet")
    assert onchain_network("TON") == "mainnet"


def test_confirm_refuses_a_testnet_claim_on_mainnet(fake_supabase, monkeypatch):
    c = _claims()
    calls = _prepare(fake_supabase, network="testnet")
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "56")
    monkeypatch.setattr(c, "verify_bnb_claim_tx", lambda **kw: pytest.fail("must not even look at the chain"))
    with pytest.raises(c.ClaimError, match="claim_wrong_network"):
        c.confirm_claim(1, "claim-x", "0x" + "11" * 32)
    assert not calls["confirmed"] and not calls["failed"]


def test_retry_refuses_a_testnet_claim_on_mainnet(fake_supabase, monkeypatch):
    c = _claims()
    calls = _prepare(fake_supabase, network="testnet", status="FAILED")
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "56")
    with pytest.raises(c.ClaimError, match="claim_wrong_network"):
        c.retry_claim(1, "claim-x", "BNB")
    assert not calls["retried"]


def test_retry_passes_the_network_to_the_database(fake_supabase, monkeypatch):
    c = _claims()
    calls = _prepare(fake_supabase, network="testnet", status="FAILED")
    fake_supabase.store["xera_external_wallets"] = [
        {"user_id": 1, "chain": "BNB", "address": Account.create().address, "status": "VERIFIED", "connection_method": "wallet"}]
    _mark_transfer_ready(fake_supabase)
    c.retry_claim(1, "claim-x", "BNB")
    assert calls["retried"][0]["p_network"] == "testnet"


def test_sign_amount_claim_stamps_the_network(fake_supabase, monkeypatch):
    c = _claims()
    seen = []
    fake_supabase.store["xera_chain_config"] = [{
        "chain": "BNB", "network": "testnet", "xera_distributor_address": DIST,
        "xera_vesting_address": "0x" + "CD" * 20, "xera_migration_address": None, "onchain_enabled": True}]
    fake_supabase.store["xera_external_wallets"] = [
        {"user_id": 1, "chain": "BNB", "address": Account.create().address, "status": "VERIFIED", "connection_method": "wallet"}]
    _mark_transfer_ready(fake_supabase)
    fake_supabase.rpc_handlers["xera_reserve_onchain_claim_amount"] = lambda p: (seen.append(p), types.SimpleNamespace(data=[{}]))[1]

    signed = c.sign_amount_claim(1, "BNB", "1.15")
    assert seen[0]["p_network"] == "testnet"
    assert signed["amount_wei"] == "1150000000000000000"

    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "56")
    c.sign_amount_claim(1, "BNB", "1.15")
    assert seen[1]["p_network"] == "mainnet"


# ------------------------------------------------------------------ C6: pending != failed

@pytest.mark.parametrize("code", ["transaction_not_found", "not_enough_confirmations", "bnb_rpc_unreachable",
                                  "rpc_chain_mismatch", "amount_mismatch", "claim_settled_event_not_found"])
def test_pending_or_unclear_results_do_not_release_the_reservation(fake_supabase, monkeypatch, code):
    c = _claims()
    calls = _prepare(fake_supabase)

    def boom(**kw):
        raise c.IndexerError(code)

    monkeypatch.setattr(c, "verify_bnb_claim_tx", boom)
    with pytest.raises(c.ClaimError, match=code):
        c.confirm_claim(1, "claim-x", "0x" + "11" * 32)
    assert calls["failed"] == []
    assert calls["confirmed"] == []


def test_only_a_reverted_transaction_fails_the_claim(fake_supabase, monkeypatch):
    c = _claims()
    calls = _prepare(fake_supabase)

    def reverted(**kw):
        raise c.IndexerError("transaction_reverted")

    monkeypatch.setattr(c, "verify_bnb_claim_tx", reverted)
    with pytest.raises(c.ClaimError, match="transaction_reverted"):
        c.confirm_claim(1, "claim-x", "0x" + "11" * 32)
    assert calls["failed"] == [{"p_reference_id": "claim-x"}]


# ------------------------------------------------------------------ C5: the verifier itself

SIG = keccak(text="ClaimSettled(address,bytes32,uint256,uint256,uint256)")
USER = Account.create().address
REF = keccak(text="claim-x")
TX = "0x" + "22" * 32


def _fake_web3(eth):
    """Stand-in for the `Web3` class: Web3(Web3.HTTPProvider(url)) -> object with .eth."""
    class _W3:
        HTTPProvider = staticmethod(lambda *_a, **_k: None)

        def __new__(cls, *_a, **_k):
            return types.SimpleNamespace(eth=eth)
    return _W3


class _FakeEth:
    def __init__(self, *, chain_id, block_number, receipt_block, status=1):
        self.chain_id = chain_id
        self.block_number = block_number
        data = abi_encode(["uint256", "uint256", "uint256"], [1_150_000_000_000_000_000, 287_500_000_000_000_000, 862_500_000_000_000_000])
        log = types.SimpleNamespace(
            address=DIST,
            topics=[SIG, b"\x00" * 12 + bytes.fromhex(USER[2:]), REF],
            data=data)
        self._receipt = types.SimpleNamespace(status=status, logs=[log], blockNumber=receipt_block)

    def get_transaction_receipt(self, _h):
        return self._receipt


def _verify(monkeypatch, **eth_kw):
    ind = importlib.import_module("xera.chain.onchain_indexer")
    eth = _FakeEth(**eth_kw)
    monkeypatch.setenv("XERA_BNB_RPC_URL", "http://rpc.invalid")
    monkeypatch.setattr(ind, "Web3", _fake_web3(eth))
    return ind.verify_bnb_claim_tx(
        tx_hash=TX, distributor_address=DIST, expected_user=USER,
        expected_reference_id_bytes32=REF, expected_total_amount_wei=1_150_000_000_000_000_000), ind


def test_verifier_accepts_a_correct_final_claim(fake_supabase, monkeypatch):
    result, _ = _verify(monkeypatch, chain_id=97, block_number=100, receipt_block=100)
    assert result["block_number"] == 100


def test_verifier_rejects_an_rpc_on_the_wrong_chain(fake_supabase, monkeypatch):
    with pytest.raises(Exception, match="rpc_chain_mismatch"):
        _verify(monkeypatch, chain_id=56, block_number=100, receipt_block=100)   # app is on 97, RPC says 56


def test_mainnet_needs_confirmations_before_a_claim_counts(fake_supabase, monkeypatch):
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "56")
    with pytest.raises(Exception, match="not_enough_confirmations"):
        _verify(monkeypatch, chain_id=56, block_number=102, receipt_block=100)   # 3 deep, needs 5
    result, _ = _verify(monkeypatch, chain_id=56, block_number=104, receipt_block=100)   # 5 deep
    assert result["block_number"] == 100


def test_confirmation_depth_is_configurable(fake_supabase, monkeypatch):
    monkeypatch.setenv("XERA_BNB_CHAIN_ID", "56")
    monkeypatch.setenv("XERA_BNB_CONFIRMATIONS", "12")
    with pytest.raises(Exception, match="not_enough_confirmations"):
        _verify(monkeypatch, chain_id=56, block_number=104, receipt_block=100)


def test_verifier_still_rejects_reverted_and_wrong_amount(fake_supabase, monkeypatch):
    with pytest.raises(Exception, match="transaction_reverted"):
        _verify(monkeypatch, chain_id=97, block_number=100, receipt_block=100, status=0)
    ind = importlib.import_module("xera.chain.onchain_indexer")
    eth = _FakeEth(chain_id=97, block_number=100, receipt_block=100)
    monkeypatch.setenv("XERA_BNB_RPC_URL", "http://rpc.invalid")
    monkeypatch.setattr(ind, "Web3", _fake_web3(eth))
    with pytest.raises(Exception, match="amount_mismatch"):
        ind.verify_bnb_claim_tx(tx_hash=TX, distributor_address=DIST, expected_user=USER,
                                expected_reference_id_bytes32=REF, expected_total_amount_wei=1)
