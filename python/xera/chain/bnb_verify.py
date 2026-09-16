"""
BNB wallet-link verification (section 8): nonce-based ownership proof via a
standard wallet signature. Never requests or stores private keys/seed
phrases — this module only ever handles a public address and a signature
over a server-issued nonce message.
"""

from eth_account.messages import encode_defunct
from eth_account import Account


def build_link_message(nonce: str, address: str) -> str:
    """
    Human-readable message the user's wallet will show them to sign — kept
    unambiguous about what it authorizes and non-reusable (embeds the nonce).
    """
    return (
        "Link this wallet to your EVOS Hub XERA account.\n\n"
        f"Address: {address}\n"
        f"Nonce: {nonce}\n\n"
        "This request will not move any funds."
    )


def verify_bnb_signature(*, address: str, nonce: str, signature: str) -> bool:
    message = build_link_message(nonce, address)
    encoded = encode_defunct(text=message)
    try:
        recovered = Account.recover_message(encoded, signature=signature)
    except Exception:
        return False
    return recovered.lower() == address.lower()
