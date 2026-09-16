from eth_account import Account
from eth_account.messages import encode_defunct

from xera.chain.bnb_verify import build_link_message, verify_bnb_signature


def test_verify_bnb_signature_accepts_a_correctly_signed_nonce():
    acct = Account.create()
    nonce = "abc123"
    message = build_link_message(nonce, acct.address)
    signed = acct.sign_message(encode_defunct(text=message))

    assert verify_bnb_signature(address=acct.address, nonce=nonce, signature=signed.signature.hex())


def test_verify_bnb_signature_rejects_signature_from_a_different_wallet():
    acct = Account.create()
    other = Account.create()
    nonce = "abc123"
    message = build_link_message(nonce, acct.address)
    signed = other.sign_message(encode_defunct(text=message))  # wrong signer

    assert not verify_bnb_signature(address=acct.address, nonce=nonce, signature=signed.signature.hex())


def test_verify_bnb_signature_rejects_a_tampered_nonce():
    acct = Account.create()
    message = build_link_message("original-nonce", acct.address)
    signed = acct.sign_message(encode_defunct(text=message))

    # Verifier reconstructs the message using a different nonce than what was signed.
    assert not verify_bnb_signature(address=acct.address, nonce="tampered-nonce", signature=signed.signature.hex())


def test_verify_bnb_signature_rejects_garbage_signature():
    acct = Account.create()
    assert not verify_bnb_signature(address=acct.address, nonce="n", signature="0xnotasignature")
