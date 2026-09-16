"""
TON claim signing — the canonical payload/hash construction here MUST
produce byte-identical results to `mining_distributor.tact`'s `Claim`
handler (see blockchain/ton/contracts/mining_distributor.tact, the cell
built right before `checkSignature`). If you change one side, change both,
and regenerate the test vectors in tests/test_ton_claim_signer.py.

Canonical payload (a TON cell, NOT a flat byte concatenation — see
"Why a cell, not raw bytes" below):

    cell = beginCell()
        .storeUint(0x2000, 32)        // opcode — the Claim message's tag
        .storeUint(queryId, 64)       // caller-supplied, echoed back, not security-relevant
        .storeAddress(user)           // TON StdAddress: 2-bit tag + 1-bit anycast + int8 workchain + uint256 hash (TEP-0002 / TL-B addr_std$10)
        .storeCoins(amount)           // VarUInteger 16 — TON's standard variable-length nanocoin encoding
        .storeUint(referenceId, 256)  // uint256 — sha256 of the off-chain reference_id STRING (see reference_id_to_uint256)
        .storeUint(deadline, 64)      // unix seconds
        .endCell()

    signature = Ed25519(sk, cell.hash())

`cell.hash()` is TON's standard cell representation hash (the same hash
`checkSignature()` in Tact/FunC uses) — NOT sha256 of the serialized bits.
This is why the signer needs an actual TON cell library (pytoniq-core)
rather than hashlib: a flat-byte hash would NOT match what the contract
computes, silently breaking every signature.

Why a cell, not raw bytes: this reuses TON's own canonical, unambiguous
binary serialization (same one the contract's `beginCell()...endCell()`
produces) instead of inventing a second bespoke wire format on the Python
side that could subtly diverge from the Tact side (endianness, integer
width, address encoding) — the two sides describe the SAME structure once,
in each language's native cell-building API, and cross-verification is
"do these two independently-built cells hash the same," which
tests/test_ton_claim_signer.py's fixed vectors check.
"""

import hashlib

from nacl.signing import SigningKey
from pytoniq_core import Address, Builder

CLAIM_OPCODE = 0x2000


def reference_id_to_uint256(reference_id: str) -> int:
    """
    referenceId on TON is a uint256, but Supabase's reference_id is an
    arbitrary string (mirrors BNB's `keccak256(bytes(reference_id))`-as-
    bytes32 convention — see xera.chain.eip712_signer). TON side uses
    sha256 instead of keccak, since that's what's cheaply available/
    idiomatic in FunC/Tact — there is no cryptographic requirement that
    BNB and TON derive the identifier the same way, only that each chain
    is internally consistent and the backend derives it identically to
    however the on-chain event is later matched back to `reference_id` in
    xera_onchain_claims (see xera.chain.onchain_indexer's TON confirmation
    path, which recomputes this exact same value to match against it).
    """
    return int.from_bytes(hashlib.sha256(reference_id.encode("utf-8")).digest(), "big")


def build_claim_cell(*, query_id: int, user_address: str, amount_nano: int, reference_id: str, deadline_unix: int) -> Builder:
    b = Builder()
    b.store_uint(CLAIM_OPCODE, 32)
    b.store_uint(query_id, 64)
    b.store_address(Address(user_address))
    b.store_coins(amount_nano)
    b.store_uint(reference_id_to_uint256(reference_id), 256)
    b.store_uint(deadline_unix, 64)
    return b


def claim_cell_hash(**kwargs) -> bytes:
    return build_claim_cell(**kwargs).end_cell().hash


def sign_ton_claim(*, signing_key_hex: str, query_id: int, user_address: str, amount_nano: int,
                    reference_id: str, deadline_unix: int) -> dict:
    """
    Returns everything the TON `Claim` message needs: the signature bytes
    (hex), plus every field echoed back so the caller can construct the
    message without re-deriving anything.
    """
    sk = SigningKey(bytes.fromhex(signing_key_hex))
    digest = claim_cell_hash(
        query_id=query_id, user_address=user_address, amount_nano=amount_nano,
        reference_id=reference_id, deadline_unix=deadline_unix,
    )
    signature = sk.sign(digest).signature

    return {
        "query_id": query_id,
        "user_address": user_address,
        "amount_nano": amount_nano,
        "reference_id": reference_id,
        "reference_id_uint256": reference_id_to_uint256(reference_id),
        "deadline_unix": deadline_unix,
        "cell_hash_hex": digest.hex(),
        "signature_hex": signature.hex(),
        "signer_public_key_hex": sk.verify_key.encode().hex(),
    }


def ton_signer_public_key_hex() -> str:
    from xera.chain.config import claim_signer_ton_key
    sk = SigningKey(bytes.fromhex(claim_signer_ton_key()))
    return sk.verify_key.encode().hex()


def sign_claim_configured(*, query_id: int, user_address: str, amount_nano: int,
                           reference_id: str, deadline_unix: int) -> dict:
    """Same as sign_ton_claim but reads the ClaimSigner's TON key from the
    app's separated secret store (xera.chain.config), for use by the real
    claim-signing service rather than tests/tooling."""
    from xera.chain.config import claim_signer_ton_key
    return sign_ton_claim(
        signing_key_hex=claim_signer_ton_key(),
        query_id=query_id, user_address=user_address, amount_nano=amount_nano,
        reference_id=reference_id, deadline_unix=deadline_unix,
    )
