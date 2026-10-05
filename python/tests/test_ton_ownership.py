"""
verify_ton_ownership() — the check that makes a TON wallet "verified".
Uses real Ed25519 signatures and real wallet StateInit cells; nothing about
the cryptography is mocked.
"""
import base64
import os

from nacl.signing import SigningKey
from pytoniq_core import StateInit, begin_cell

from xera.chain.ton_verify import build_ton_proof_message, verify_ton_ownership

DOMAINS = {"evoshub.xyz"}
NOW = 1_800_000_000


def _wallet(pub: bytes, layout="v4"):
    """A wallet StateInit + the address it hashes to."""
    code = begin_cell().store_uint(0xC0DE, 16).end_cell()
    if layout == "v4":
        data = begin_cell().store_uint(0, 32).store_uint(698983191, 32).store_bytes(pub).store_bit(0).end_cell()
    else:  # v5
        data = begin_cell().store_bit(1).store_uint(0, 32).store_uint(2147483409, 32).store_bytes(pub).store_bit(0).end_cell()
    si = StateInit(code=code, data=data).serialize()
    return base64.b64encode(si.to_boc()).decode(), si.hash


def _proof(key: SigningKey, address_hash: bytes, *, domain="evoshub.xyz", ts=NOW, payload="nonce-1"):
    digest = build_ton_proof_message(workchain=0, address_hash=address_hash, domain=domain, timestamp=ts, payload=payload)
    return base64.b64encode(key.sign(digest).signature).decode()


def _verify(**over):
    base = dict(domain="evoshub.xyz", timestamp=NOW, payload="nonce-1", allowed_domains=DOMAINS, now=NOW)
    base.update(over)
    return verify_ton_ownership(**base)


def _good(layout="v4"):
    key = SigningKey.generate()
    pub = key.verify_key.encode()
    state_init, addr_hash = _wallet(pub, layout)
    return dict(
        address="0:" + addr_hash.hex(),
        signature_b64=_proof(key, addr_hash),
        wallet_public_key_hex=pub.hex(),
        wallet_state_init_b64=state_init,
    )


def test_accepts_a_genuine_v4_and_v5_wallet_proof():
    assert _verify(**_good("v4"))
    assert _verify(**_good("v5"))


def test_rejects_attacker_signing_with_their_own_key_for_a_victims_address():
    victim = _good()
    attacker = SigningKey.generate()
    attacker_pub = attacker.verify_key.encode()
    attacker_state_init, _ = _wallet(attacker_pub)
    victim_hash = bytes.fromhex(victim["address"][2:])

    forged = dict(
        address=victim["address"],                       # claims the VICTIM's address
        signature_b64=_proof(attacker, victim_hash),     # validly signed by the attacker's key
        wallet_public_key_hex=attacker_pub.hex(),
        wallet_state_init_b64=attacker_state_init,       # attacker's own wallet init
    )
    # The signature alone is valid for the attacker's key...
    from xera.chain.ton_verify import verify_ton_proof
    assert verify_ton_proof(address=forged["address"], domain="evoshub.xyz", timestamp=NOW, payload="nonce-1",
                            signature_b64=forged["signature_b64"], wallet_public_key_hex=forged["wallet_public_key_hex"])
    # ...but ownership is rejected: the state init does not hash to the victim's address.
    assert not _verify(**forged)


def test_rejects_when_state_init_matches_address_but_key_is_not_inside_it():
    good = _good()
    other = SigningKey.generate()
    forged = dict(good, signature_b64=_proof(other, bytes.fromhex(good["address"][2:])),
                  wallet_public_key_hex=other.verify_key.encode().hex())
    assert not _verify(**forged)


def test_rejects_missing_state_init():
    good = _good()
    assert _verify(**good)                                   # baseline
    assert not _verify(**dict(good, wallet_state_init_b64=""))


def test_rejects_unknown_domain_even_with_a_valid_signature_for_that_domain():
    key = SigningKey.generate(); pub = key.verify_key.encode(); si, h = _wallet(pub)
    evil = dict(address="0:" + h.hex(), signature_b64=_proof(key, h, domain="evil.example"),
                wallet_public_key_hex=pub.hex(), wallet_state_init_b64=si)
    assert not _verify(domain="evil.example", **evil)


def test_rejects_stale_timestamp():
    key = SigningKey.generate(); pub = key.verify_key.encode(); si, h = _wallet(pub)
    old = NOW - 10_000
    stale = dict(address="0:" + h.hex(), signature_b64=_proof(key, h, ts=old),
                 wallet_public_key_hex=pub.hex(), wallet_state_init_b64=si)
    assert not _verify(timestamp=old, **stale)


def test_rejects_a_replayed_proof_with_a_different_nonce():
    good = _good()
    assert not _verify(payload="a-different-nonce", **good)


def test_garbage_input_fails_closed_never_raises():
    assert not _verify(address="not-an-address", signature_b64="x", wallet_public_key_hex="zz", wallet_state_init_b64="!!")
