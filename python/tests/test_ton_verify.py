import base64
import os

from nacl.signing import SigningKey

from xera.chain.ton_verify import build_ton_proof_message, verify_ton_proof, decode_ton_address


def _make_ton_address(workchain: int, address_hash: bytes) -> str:
    """Builds a well-formed-length (36 byte) TEP-0002 address for testing.
    CRC16 bytes are dummy — decode_ton_address (by design) doesn't verify
    them; only length/workchain/hash extraction is under test here."""
    tag = 0x11
    raw = bytes([tag, workchain & 0xFF]) + address_hash + b"\x00\x00"
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


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
