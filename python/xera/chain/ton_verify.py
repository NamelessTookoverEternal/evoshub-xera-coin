"""
TON wallet-link verification (section 8): TON Connect's ton_proof flow.

Never requests or stores private keys/seed phrases — the frontend's
TON Connect SDK produces a `ton_proof` object (payload/timestamp/domain/
signature) signed by the wallet's ed25519 key; this module only verifies
that signature against the wallet's already-known public key (obtained
from the TonConnect `wallet_info` `Account` payload, not derived here).

Message construction follows the TON Connect ton_proof spec (v2):

    message = "ton-proof-item-v2/"
              || workchain (4 bytes, big-endian int32)
              || address_hash (32 bytes)
              || domain_len (4 bytes, little-endian uint32)
              || domain (utf-8)
              || timestamp (8 bytes, little-endian uint64)
              || payload (utf-8, the nonce we issued)

    full_message = 0xffff || "ton-connect" || sha256(message)
    signature     = Ed25519Sign(wallet_privkey, sha256(full_message))

We verify with PyNaCl (`nacl.signing.VerifyKey`) against the wallet's
public key. Any parsing failure or signature mismatch returns False —
this module never raises to the caller for attacker-controlled input.
"""

import base64
import hashlib
import struct

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

_TON_PROOF_PREFIX = b"ton-proof-item-v2/"
_TON_CONNECT_PREFIX = b"ton-connect"


def decode_ton_address(address: str) -> tuple[int, bytes]:
    """
    Decodes a TEP-0002 user-friendly TON address (base64 or base64url,
    36 bytes: 1 tag + 1 workchain + 32 hash + 2 crc16) into
    (workchain, hash). Raises ValueError on malformed input.
    """
    raw = address.replace("-", "+").replace("_", "/")
    padding = "=" * (-len(raw) % 4)
    data = base64.b64decode(raw + padding)
    if len(data) != 36:
        raise ValueError("invalid TON address length")
    workchain_byte = data[1]
    workchain = workchain_byte if workchain_byte < 128 else workchain_byte - 256
    address_hash = data[2:34]
    return workchain, address_hash


def build_ton_proof_message(*, workchain: int, address_hash: bytes, domain: str, timestamp: int, payload: str) -> bytes:
    domain_bytes = domain.encode("utf-8")
    message = (
        _TON_PROOF_PREFIX
        + struct.pack(">i", workchain)
        + address_hash
        + struct.pack("<I", len(domain_bytes))
        + domain_bytes
        + struct.pack("<Q", timestamp)
        + payload.encode("utf-8")
    )
    full_message = b"\xff\xff" + _TON_CONNECT_PREFIX + hashlib.sha256(message).digest()
    return hashlib.sha256(full_message).digest()


def verify_ton_proof(*, address: str, domain: str, timestamp: int, payload: str,
                      signature_b64: str, wallet_public_key_hex: str) -> bool:
    try:
        workchain, address_hash = decode_ton_address(address)
        digest = build_ton_proof_message(
            workchain=workchain, address_hash=address_hash,
            domain=domain, timestamp=timestamp, payload=payload,
        )
        signature = base64.b64decode(signature_b64)
        verify_key = VerifyKey(bytes.fromhex(wallet_public_key_hex))
        verify_key.verify(digest, signature)
        return True
    except (BadSignatureError, ValueError, Exception):
        return False
