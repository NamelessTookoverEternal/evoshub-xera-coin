"""
Produces the exact EIP-712 signature XeraMiningDistributor.claim() verifies
on-chain (blockchain/bnb/contracts/XeraMiningDistributor.sol).

Domain and struct here MUST stay byte-for-byte in sync with the Solidity
side:

    EIP712("XeraMiningDistributor", "1")
    Claim(address user,uint256 amount,bytes32 referenceId,uint256 deadline)

If either side changes independently, every signature this module produces
becomes worthless (the contract will reject them as invalid signatures) —
which is the safe failure mode, not a silent one.

The signing key (XERA_CLAIM_SIGNER_PRIVATE_KEY) is deliberately isolated
here — see chain/config.py docstring. Nothing else imports this module's
private key handling.
"""

import os

from eth_account import Account
from eth_account.messages import encode_typed_data

from xera.chain.config import ChainConfigError


def _signer_account() -> Account:
    pk = os.getenv("XERA_CLAIM_SIGNER_PRIVATE_KEY", "")
    if not pk:
        raise ChainConfigError("claim_signer_not_configured")
    return Account.from_key(pk)


def signer_address() -> str:
    return _signer_account().address


def sign_bnb_claim(*, user_address: str, amount_wei: int, reference_id_bytes32: bytes,
                    deadline_unix: int, chain_id: int, verifying_contract: str) -> str:
    """
    Returns a 0x-prefixed hex signature over the typed-data claim, matching
    XeraMiningDistributor's CLAIM_TYPEHASH exactly.
    """
    account = _signer_account()

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
            "name": "XeraMiningDistributor",
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": verifying_contract,
        },
        "message": {
            "user": user_address,
            "amount": amount_wei,
            "referenceId": reference_id_bytes32,
            "deadline": deadline_unix,
        },
    }

    encoded = encode_typed_data(full_message=typed_data)
    signed = account.sign_message(encoded)
    return signed.signature.hex() if signed.signature.hex().startswith("0x") else "0x" + signed.signature.hex()
