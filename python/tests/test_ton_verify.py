import base64
import os

from nacl.signing import SigningKey
from pytoniq_core import Address as _TonAddress

from xera.chain.ton_verify import build_ton_proof_message, verify_ton_proof, decode_ton_address


def _make_ton_address(workchain: int, address_hash: bytes) -> str:
    """Builds a real, CRC16-valid TEP-0002 address for testing — via
    pytoniq-core's own Address encoder, so these fixtures are genuinely
    decodable addresses (per the hardening pass: decode_ton_address now
    validates the checksum for real, so a dummy-CRC fixture would
    correctly be rejected as malformed, same as it should be for any
    real corrupted/tampered address a client might submit)."""
    return _TonAddress((workchain, address_hash)).to_str(is_bounceable=True, is_url_safe=True)


def test_verify_ton_proof_accepts_a_correctly_signed_proof():
    signing_key = SigningKey.generate()
    address_hash = os.urandom(32)
    address = _make_ton_address(0, address_hash)

    domain = "evoshub.xyz"
    timestamp = 1_700_000_000
    payload = "server-issued-nonce-abc"

    digest = build_ton_proof_message(workchain=0, address_hash=address_hash, domain=domain, timestamp=timestamp, payload=payload)
    signature = signing_key.sign(digest).signature

    ok = verify_ton_proof(
        address=address, domain=domain, timestamp=timestamp, payload=payload,
        signature_b64=base64.b64encode(signature).decode("ascii"),
        wallet_public_key_hex=signing_key.verify_key.encode().hex(),
    )
    assert ok


def test_verify_ton_proof_rejects_signature_from_a_different_key():
    signing_key = SigningKey.generate()
    other_key = SigningKey.generate()
    address_hash = os.urandom(32)
    address = _make_ton_address(0, address_hash)

    digest = build_ton_proof_message(workchain=0, address_hash=address_hash, domain="d", timestamp=1, payload="p")
    signature = signing_key.sign(digest).signature  # signed by the WRONG key

    ok = verify_ton_proof(
        address=address, domain="d", timestamp=1, payload="p",
        signature_b64=base64.b64encode(signature).decode("ascii"),
        wallet_public_key_hex=other_key.verify_key.encode().hex(),  # verified against a different key
    )
    assert not ok


def test_verify_ton_proof_rejects_tampered_payload():
    signing_key = SigningKey.generate()
    address_hash = os.urandom(32)
    address = _make_ton_address(0, address_hash)

    digest = build_ton_proof_message(workchain=0, address_hash=address_hash, domain="d", timestamp=1, payload="original")
    signature = signing_key.sign(digest).signature

    ok = verify_ton_proof(
        address=address, domain="d", timestamp=1, payload="tampered",  # different payload than what was signed
        signature_b64=base64.b64encode(signature).decode("ascii"),
        wallet_public_key_hex=signing_key.verify_key.encode().hex(),
    )
    assert not ok


def test_verify_ton_proof_fails_closed_on_malformed_address():
    ok = verify_ton_proof(
        address="not-a-valid-address", domain="d", timestamp=1, payload="p",
        signature_b64=base64.b64encode(b"\x00" * 64).decode("ascii"),
        wallet_public_key_hex="00" * 32,
    )
    assert not ok


def test_decode_ton_address_round_trips_workchain_and_hash():
    address_hash = os.urandom(32)
    address = _make_ton_address(-1, address_hash)  # masterchain
    workchain, hash_out = decode_ton_address(address)
    assert workchain == -1
    assert hash_out == address_hash


def test_decode_ton_address_rejects_a_real_address_with_a_corrupted_checksum():
    """Section 9's explicit ask: don't only test with artificially
    constructed dummy-CRC addresses — start from a real, valid one and
    corrupt it, proving the checksum is actually enforced."""
    valid = _TonAddress((0, os.urandom(32))).to_str(is_bounceable=True, is_url_safe=True)
    # Flip the last character (part of the crc16 tail) to invalidate the checksum.
    last = valid[-1]
    replacement = "A" if last != "A" else "B"
    corrupted = valid[:-1] + replacement
    try:
        decode_ton_address(corrupted)
        assert False, "a checksum-corrupted address must not decode successfully"
    except ValueError:
        pass


def test_decode_ton_address_rejects_a_known_real_mainnet_address_with_one_bit_flipped():
    """Not an artificially constructed fixture — a real, previously-valid
    TEP-0002 address, tampered by a single bit flip."""
    real_valid_address = "EQD4FPq-PRDieyQKkizFTRtSDyucUIqrj0v_zXJmqaDp6_0t"
    tampered = real_valid_address[:-1] + ("X" if real_valid_address[-1] != "X" else "Y")
    try:
        decode_ton_address(tampered)
        assert False, "a tampered real address must not decode successfully"
    except ValueError:
        pass
    # But the original, untampered real address decodes fine.
    workchain, address_hash = decode_ton_address(real_valid_address)
    assert workchain == 0
    assert len(address_hash) == 32
