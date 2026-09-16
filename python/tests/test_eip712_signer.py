import os

from eth_account import Account
from eth_account.messages import encode_typed_data

from xera.chain import eip712_signer


def test_sign_bnb_claim_is_recoverable_to_the_signer(monkeypatch):
    acct = Account.create()
    monkeypatch.setenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", acct.key.hex())
    user_addr = Account.create().address
    contract_addr = Account.create().address

    reference_id_bytes32 = (b"\x11" * 32)
    sig = eip712_signer.sign_bnb_claim(
        user_address=user_addr,
        amount_wei=1000 * 10**18,
        reference_id_bytes32=reference_id_bytes32,
        deadline_unix=9999999999,
        chain_id=97,
        verifying_contract=contract_addr,
    )

    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Claim": [
                {"name": "user", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "referenceId", "type": "bytes32"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "Claim",
        "domain": {
            "name": "XeraMiningDistributor", "version": "1",
            "chainId": 97, "verifyingContract": contract_addr,
        },
        "message": {
            "user": user_addr,
            "amount": 1000 * 10**18,
            "referenceId": reference_id_bytes32,
            "deadline": 9999999999,
        },
    }
    encoded = encode_typed_data(full_message=typed_data)
    recovered = Account.recover_message(encoded, signature=sig)
    assert recovered == acct.address


def test_signer_address_matches_the_configured_key(monkeypatch):
    acct = Account.create()
    monkeypatch.setenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", acct.key.hex())
    assert eip712_signer.signer_address() == acct.address


def test_a_different_domain_produces_a_non_recoverable_signature_for_the_wrong_contract(monkeypatch):
    """Sanity check that the domain actually participates in the signature —
    signing for one contract and recovering against a DIFFERENT contract's
    domain must NOT recover to the signer (this is what makes contract
    confusion attacks fail on-chain)."""
    acct = Account.create()
    monkeypatch.setenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", acct.key.hex())
    user_addr = Account.create().address
    contract_addr = Account.create().address
    other_contract_addr = Account.create().address

    reference_id_bytes32 = b"\x22" * 32
    sig = eip712_signer.sign_bnb_claim(
        user_address=user_addr,
        amount_wei=1,
        reference_id_bytes32=reference_id_bytes32,
        deadline_unix=9999999999,
        chain_id=97,
        verifying_contract=contract_addr,
    )

    wrong_domain_typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Claim": [
                {"name": "user", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "referenceId", "type": "bytes32"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "Claim",
        "domain": {
            "name": "XeraMiningDistributor", "version": "1",
            "chainId": 97, "verifyingContract": other_contract_addr,  # different contract
        },
        "message": {
            "user": user_addr,
            "amount": 1,
            "referenceId": reference_id_bytes32,
            "deadline": 9999999999,
        },
    }
    encoded = encode_typed_data(full_message=wrong_domain_typed_data)
    recovered = Account.recover_message(encoded, signature=sig)
    assert recovered != acct.address
