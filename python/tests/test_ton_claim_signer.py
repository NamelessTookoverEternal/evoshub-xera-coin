"""
Deterministic test vectors for the TON claim signer. These EXACT values
are also asserted from the TypeScript side in
blockchain/ton/tests/XeraMiningDistributor.claimSignature.spec.ts, which
submits the same signature to the actual compiled contract in a TON
sandbox and confirms it's accepted. If you change ton_claim_signer.py's
cell layout, both files break — that's intentional, it's the tripwire for
the two implementations diverging.
"""

from xera.chain.ton_claim_signer import sign_ton_claim, reference_id_to_uint256, claim_cell_hash

FIXED_SEED_HEX = "11" * 32
FIXED_USER_ADDRESS = "0:" + "22" * 32
FIXED_QUERY_ID = 42
FIXED_AMOUNT_NANO = 1000 * 10**9
FIXED_REFERENCE_ID = "mining-session-abc123"
FIXED_DEADLINE = 9999999999

# Pinned — cross-checked byte-for-byte against the TypeScript/TON-sandbox
# test using @ton/core's beginCell()/endCell()/hash().
EXPECTED_CELL_HASH_HEX = "cc0a81fa853e118ee7282b705d547d74a3097b81b2db4f33a888df57cf5d196e"


def test_reference_id_derivation_is_sha256_of_the_utf8_string():
    import hashlib
    expected = int.from_bytes(hashlib.sha256(FIXED_REFERENCE_ID.encode("utf-8")).digest(), "big")
    assert reference_id_to_uint256(FIXED_REFERENCE_ID) == expected


def test_fixed_vector_cell_hash_matches_the_pinned_cross_checked_value():
    digest = claim_cell_hash(
        query_id=FIXED_QUERY_ID, user_address=FIXED_USER_ADDRESS, amount_nano=FIXED_AMOUNT_NANO,
        reference_id=FIXED_REFERENCE_ID, deadline_unix=FIXED_DEADLINE,
    )
    assert digest.hex() == EXPECTED_CELL_HASH_HEX


def test_sign_ton_claim_produces_a_64_byte_ed25519_signature():
    result = sign_ton_claim(
        signing_key_hex=FIXED_SEED_HEX, query_id=FIXED_QUERY_ID, user_address=FIXED_USER_ADDRESS,
        amount_nano=FIXED_AMOUNT_NANO, reference_id=FIXED_REFERENCE_ID, deadline_unix=FIXED_DEADLINE,
    )
    assert result["cell_hash_hex"] == EXPECTED_CELL_HASH_HEX
    assert len(bytes.fromhex(result["signature_hex"])) == 64


def test_changing_the_user_changes_the_hash_and_therefore_invalidates_the_signature():
    other_user = "0:" + "33" * 32
    digest_a = claim_cell_hash(query_id=FIXED_QUERY_ID, user_address=FIXED_USER_ADDRESS,
                                amount_nano=FIXED_AMOUNT_NANO, reference_id=FIXED_REFERENCE_ID, deadline_unix=FIXED_DEADLINE)
    digest_b = claim_cell_hash(query_id=FIXED_QUERY_ID, user_address=other_user,
                                amount_nano=FIXED_AMOUNT_NANO, reference_id=FIXED_REFERENCE_ID, deadline_unix=FIXED_DEADLINE)
    assert digest_a != digest_b


def test_changing_the_amount_changes_the_hash():
    digest_a = claim_cell_hash(query_id=FIXED_QUERY_ID, user_address=FIXED_USER_ADDRESS,
                                amount_nano=FIXED_AMOUNT_NANO, reference_id=FIXED_REFERENCE_ID, deadline_unix=FIXED_DEADLINE)
    digest_b = claim_cell_hash(query_id=FIXED_QUERY_ID, user_address=FIXED_USER_ADDRESS,
                                amount_nano=FIXED_AMOUNT_NANO + 1, reference_id=FIXED_REFERENCE_ID, deadline_unix=FIXED_DEADLINE)
    assert digest_a != digest_b


def test_changing_the_reference_id_changes_the_hash():
    digest_a = claim_cell_hash(query_id=FIXED_QUERY_ID, user_address=FIXED_USER_ADDRESS,
                                amount_nano=FIXED_AMOUNT_NANO, reference_id=FIXED_REFERENCE_ID, deadline_unix=FIXED_DEADLINE)
    digest_b = claim_cell_hash(query_id=FIXED_QUERY_ID, user_address=FIXED_USER_ADDRESS,
                                amount_nano=FIXED_AMOUNT_NANO, reference_id="different-session", deadline_unix=FIXED_DEADLINE)
    assert digest_a != digest_b


def test_changing_the_deadline_changes_the_hash():
    digest_a = claim_cell_hash(query_id=FIXED_QUERY_ID, user_address=FIXED_USER_ADDRESS,
                                amount_nano=FIXED_AMOUNT_NANO, reference_id=FIXED_REFERENCE_ID, deadline_unix=FIXED_DEADLINE)
    digest_b = claim_cell_hash(query_id=FIXED_QUERY_ID, user_address=FIXED_USER_ADDRESS,
                                amount_nano=FIXED_AMOUNT_NANO, reference_id=FIXED_REFERENCE_ID, deadline_unix=FIXED_DEADLINE + 1)
    assert digest_a != digest_b


def test_changing_the_query_id_changes_the_hash():
    digest_a = claim_cell_hash(query_id=FIXED_QUERY_ID, user_address=FIXED_USER_ADDRESS,
                                amount_nano=FIXED_AMOUNT_NANO, reference_id=FIXED_REFERENCE_ID, deadline_unix=FIXED_DEADLINE)
    digest_b = claim_cell_hash(query_id=FIXED_QUERY_ID + 1, user_address=FIXED_USER_ADDRESS,
                                amount_nano=FIXED_AMOUNT_NANO, reference_id=FIXED_REFERENCE_ID, deadline_unix=FIXED_DEADLINE)
    assert digest_a != digest_b
