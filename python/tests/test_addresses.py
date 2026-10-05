import base64
import os

import pytest
from eth_account import Account
from eth_utils import to_checksum_address
from pytoniq_core import Address

from xera.chain.addresses import AddressError, normalize_address, normalize_bnb_address, normalize_ton_address


def _code(fn, *a):
    with pytest.raises(AddressError) as e:
        fn(*a)
    return str(e.value)


# ---------------- BNB ----------------

def test_bnb_accepts_checksummed_lower_and_upper_and_returns_checksummed():
    addr = Account.create().address
    assert normalize_bnb_address(addr) == addr
    assert normalize_bnb_address(addr.lower()) == addr
    assert normalize_bnb_address("0x" + addr[2:].upper()) == addr
    assert normalize_bnb_address(f"  {addr}  ") == addr


def test_bnb_rejects_mixed_case_with_bad_checksum():
    addr = Account.create().address
    flipped = "0x" + addr[2:].swapcase()          # still valid hex, checksum now wrong
    if flipped[2:] in (flipped[2:].lower(), flipped[2:].upper()):
        pytest.skip("random address had no letters to flip")
    assert _code(normalize_bnb_address, flipped) == "bnb_checksum_mismatch"


@pytest.mark.parametrize("bad", ["0x1234", "abc", "0x" + "g" * 40, "0x" + "1" * 39, "0x" + "1" * 41, "1" * 40])
def test_bnb_rejects_malformed(bad):
    assert _code(normalize_bnb_address, bad) == "invalid_bnb_address"


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_bnb_rejects_empty(empty):
    assert _code(normalize_bnb_address, empty) == "address_required"


def test_bnb_rejects_zero_address():
    assert _code(normalize_bnb_address, "0x" + "0" * 40) == "zero_address"


def test_bnb_rejects_a_seed_phrase_or_private_key_pasted_in_by_mistake():
    seed = "test test test test test test test test test test test junk"
    private_key = "0x" + os.urandom(32).hex()   # 64 hex chars — NOT a 40-char address
    assert _code(normalize_bnb_address, seed) == "invalid_bnb_address"
    assert _code(normalize_bnb_address, private_key) == "invalid_bnb_address"


# ---------------- TON ----------------

def test_ton_accepts_raw_and_friendly_forms_and_canonicalises_to_raw():
    raw = "0:" + os.urandom(32).hex()
    a = Address(raw)
    for form in (raw, a.to_str(is_bounceable=True), a.to_str(is_bounceable=False),
                 a.to_str(is_user_friendly=True, is_url_safe=False, is_bounceable=False)):
        assert normalize_ton_address(form)["raw"] == raw
    assert normalize_ton_address(raw)["display"].startswith("UQ")


def test_ton_rejects_bad_crc_masterchain_zero_and_garbage():
    raw = "0:" + os.urandom(32).hex()
    friendly = Address(raw).to_str(is_bounceable=False)
    tampered = bytearray(base64.urlsafe_b64decode(friendly))
    tampered[-1] ^= 1
    assert _code(lambda v: normalize_ton_address(v), base64.urlsafe_b64encode(bytes(tampered)).decode()) == "invalid_ton_address"
    assert _code(lambda v: normalize_ton_address(v), "-1:" + os.urandom(32).hex()) == "unsupported_ton_workchain"
    assert _code(lambda v: normalize_ton_address(v), "0:" + "00" * 32) == "zero_address"
    for bad in ("hello", "UQ123", "0xabc", "0:zz"):
        assert _code(lambda v: normalize_ton_address(v), bad) == "invalid_ton_address"
    assert _code(lambda v: normalize_ton_address(v), "") == "address_required"


def test_normalize_address_dispatches_by_chain_and_rejects_unknown():
    addr = Account.create().address
    assert normalize_address("bnb", addr.lower()) == addr
    assert normalize_address("TON", "0:" + "ab" * 32) == "0:" + "ab" * 32
    assert _code(normalize_address, "ETH", addr) == "invalid_chain"
