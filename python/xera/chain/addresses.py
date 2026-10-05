"""
Public wallet-address validation + normalisation (BNB / EVM and TON).

This is the ONLY place a user-supplied address string is turned into the form
we store and compare. It only ever handles PUBLIC addresses — nothing in the
wallet flow accepts or should accept a seed phrase, private key or password.

Why normalisation matters beyond tidiness: the database enforces "one active
verified wallet per address" with a unique index. If the same wallet could be
stored as `0xabc…` by one user and `0xAbC…` by another (or as `UQ…` / `EQ…` /
`0:…` for TON), that guarantee would silently not hold. So we always store ONE
canonical form per chain:

  * BNB: EIP-55 checksummed address.
  * TON: raw `workchain:hex64` (lowercase). A friendly form (`UQ…`) is derived
    for display only.
"""

import os
import re

from eth_utils import is_checksum_address, to_checksum_address
from pytoniq_core import Address

_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ZERO_EVM = "0x" + "0" * 40


class AddressError(Exception):
    """Short machine-readable code; routes_chain.py maps these to HTTP responses."""


def normalize_bnb_address(value: str) -> str:
    candidate = (value or "").strip()
    if not candidate:
        raise AddressError("address_required")
    if not _EVM_RE.match(candidate):
        raise AddressError("invalid_bnb_address")
    if candidate.lower() == _ZERO_EVM:
        raise AddressError("zero_address")

    body = candidate[2:]
    # All-lowercase / all-uppercase carry no checksum and are accepted (that's
    # what many wallets and explorers copy out). Mixed-case MUST be a valid
    # EIP-55 checksum — a mismatch is the classic sign of a mistyped address.
    if body != body.lower() and body != body.upper() and not is_checksum_address(candidate):
        raise AddressError("bnb_checksum_mismatch")
    return to_checksum_address(candidate)


def normalize_ton_address(value: str) -> dict:
    """
    Accepts raw (`0:abcd…`) or user-friendly (`UQ…`, `EQ…`, `0Q…`, `kQ…`,
    base64 or base64url, CRC-checked by pytoniq-core). Returns
    {"raw": canonical raw form, "display": friendly non-bounceable form}.
    """
    candidate = (value or "").strip()
    if not candidate:
        raise AddressError("address_required")
    try:
        addr = Address(candidate)
    except Exception:
        raise AddressError("invalid_ton_address")

    # Wallet contracts live on the basechain. Masterchain (-1) and anything
    # else is never a user wallet here.
    if addr.wc != 0:
        raise AddressError("unsupported_ton_workchain")
    if addr.hash_part == bytes(32):
        raise AddressError("zero_address")

    return {"raw": ton_raw(addr), "display": ton_display_from_address(addr)}


def ton_raw(addr: Address) -> str:
    return f"{addr.wc}:{addr.hash_part.hex()}"


def ton_display_from_address(addr: Address) -> str:
    testnet = os.getenv("XERA_TON_TESTNET", "false").strip().lower() == "true"
    return addr.to_str(is_user_friendly=True, is_bounceable=False, is_test_only=testnet)


def ton_display(raw_or_friendly: str) -> str:
    """Display form for an already-stored TON address; never raises."""
    try:
        return ton_display_from_address(Address(raw_or_friendly))
    except Exception:
        return raw_or_friendly


def normalize_address(chain: str, value: str) -> str:
    """Canonical stored form for the given chain (raises AddressError)."""
    chain = (chain or "").upper()
    if chain == "BNB":
        return normalize_bnb_address(value)
    if chain == "TON":
        return normalize_ton_address(value)["raw"]
    raise AddressError("invalid_chain")
