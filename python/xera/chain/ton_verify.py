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
import os
import struct
import time
from urllib.parse import urlparse

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
    # TonConnect's `account.address` is the RAW form ("0:<64 hex>"), not the
    # friendly form — accept it, otherwise every real TonConnect proof fails.
    if ":" in address:
        wc_str, _, hash_hex = address.partition(":")
        try:
            workchain = int(wc_str)
            address_hash = bytes.fromhex(hash_hex)
        except ValueError:
            raise ValueError("invalid raw TON address")
        if len(address_hash) != 32:
            raise ValueError("invalid TON address length")
        return workchain, address_hash

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


# ------------------------------------------------------------
# Ownership verification (what wallet_link.py actually calls)
# ------------------------------------------------------------
#
# verify_ton_proof() above only proves "SOME ed25519 key signed this message".
# On its own that is NOT proof of wallet ownership: the public key arrives
# from the client, so an attacker could sign with their own key while claiming
# a victim's address. The TON Connect backend-verification checklist therefore
# also requires:
#
#   1. the proof's domain is one of OUR domains (so a proof an unrelated site
#      collected from the user can't be replayed against us),
#   2. the proof's timestamp is fresh,
#   3. the wallet's StateInit hashes to the claimed address, and the public
#      key inside that StateInit is the key that signed.
#
# (3) is what binds key -> address. Supported wallet data layouts: v3/v4
# (pubkey at bit 64) and v5 (pubkey at bit 65), i.e. the wallets TonConnect
# actually returns. Anything else fails closed.

_TON_PROOF_MAX_AGE_SECONDS = int(os.getenv("XERA_TON_PROOF_MAX_AGE_SECONDS", "900"))


def allowed_proof_domains() -> set[str]:
    """
    XERA_TON_PROOF_DOMAINS (comma separated) if set, otherwise derived from
    ALLOWED_ORIGINS (the same list that already gates CORS), so there is no
    second list to keep in sync. Both host and host:port are accepted because
    wallets differ on whether the port is included.
    """
    explicit = [d.strip().lower() for d in os.getenv("XERA_TON_PROOF_DOMAINS", "").split(",") if d.strip()]
    if explicit:
        return set(explicit)
    domains: set[str] = set()
    for origin in os.getenv("ALLOWED_ORIGINS", "https://evoshub.xyz,http://localhost:5173").split(","):
        origin = origin.strip()
        if not origin:
            continue
        parsed = urlparse(origin)
        if parsed.hostname:
            domains.add(parsed.hostname.lower())
        if parsed.netloc:
            domains.add(parsed.netloc.lower())
    return domains


def _state_init_binds_address_and_key(*, state_init_b64: str, address_hash: bytes, public_key: bytes) -> bool:
    from pytoniq_core import Cell, StateInit

    try:
        cell = Cell.one_from_boc(base64.b64decode(state_init_b64))
        if cell.hash != address_hash:
            return False
        state_init = StateInit.deserialize(cell.begin_parse())
        if state_init.data is None:
            return False
        for offset in (64, 65):  # v3/v4, v5
            try:
                data = state_init.data.begin_parse()
                data.skip_bits(offset)
                if data.load_bytes(32) == public_key:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def verify_ton_ownership(*, address: str, domain: str, timestamp: int, payload: str,
                         signature_b64: str, wallet_public_key_hex: str, wallet_state_init_b64: str,
                         allowed_domains: set[str] | None = None, now: int | None = None) -> bool:
    """Full ton_proof check — fails closed on anything missing or malformed."""
    try:
        if not wallet_state_init_b64:
            return False

        domains = allowed_domains if allowed_domains is not None else allowed_proof_domains()
        if not domain or domain.strip().lower() not in domains:
            return False

        current = int(time.time()) if now is None else now
        if abs(current - int(timestamp)) > _TON_PROOF_MAX_AGE_SECONDS:
            return False

        _, address_hash = decode_ton_address(address)
        if not _state_init_binds_address_and_key(
            state_init_b64=wallet_state_init_b64,
            address_hash=address_hash,
            public_key=bytes.fromhex(wallet_public_key_hex),
        ):
            return False

        return verify_ton_proof(
            address=address, domain=domain, timestamp=timestamp, payload=payload,
            signature_b64=signature_b64, wallet_public_key_hex=wallet_public_key_hex,
        )
    except Exception:
        return False
