import types
from datetime import datetime, timedelta, timezone

from eth_account import Account
from eth_account.messages import encode_defunct

import xera.chain.bnb_verify as bnb_verify


def _install_consume_nonce_rpc(fake_supabase):
    """Fake xera_consume_wallet_nonce, mirroring the real RPC's atomic
    conditional-UPDATE semantics (single-use, bound to user/chain/address,
    expiry-checked) closely enough to exercise the service layer."""
    def handler(params):
        table = fake_supabase.store.setdefault("xera_wallet_link_nonces", [])
        match = next((r for r in table if r["nonce"] == params["p_nonce"]), None)
        if match is None:
            raise RuntimeError("nonce_not_found")
        if match.get("consumed_at") is not None:
            raise RuntimeError("nonce_already_consumed")
        expires_at = datetime.fromisoformat(str(match["expires_at"]).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_at:
            raise RuntimeError("nonce_expired")
        if match["user_id"] != params["p_user_id"] or match["chain"] != params["p_chain"]:
            raise RuntimeError("nonce_not_found")
        if str(match["address"]).lower() != str(params["p_address"]).lower():
            raise RuntimeError("nonce_address_mismatch")

        match["consumed_at"] = datetime.now(timezone.utc).isoformat()
        return types.SimpleNamespace(data=[match])

    fake_supabase.rpc_handlers["xera_consume_wallet_nonce"] = handler


def _install_link_wallet_rpc(fake_supabase):
    """Fake xera_link_external_wallet: enforces cooldown + replaces any
    existing VERIFIED row for (user, chain), mirroring the real RPC's
    behavior closely enough to exercise the service layer."""
    cooldowns = {}

    def handler(params):
        key = (params["p_user_id"], params["p_chain"])
        last = cooldowns.get(key)
        if last and (datetime.now(timezone.utc) - last).total_seconds() < params["p_cooldown_seconds"]:
            raise RuntimeError("wallet_change_cooldown_active")

        table = fake_supabase.store.setdefault("xera_external_wallets", [])
        for row in table:
            if row["user_id"] == params["p_user_id"] and row["chain"] == params["p_chain"] and row["status"] == "VERIFIED":
                row["status"] = "REPLACED"

        new_row = {
            "id": len(table) + 1,
            "user_id": params["p_user_id"],
            "chain": params["p_chain"],
            "address": params["p_address"],
            "status": "VERIFIED",
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "linked_at": datetime.now(timezone.utc).isoformat(),
        }
        table.append(new_row)
        cooldowns[key] = datetime.now(timezone.utc)
        return types.SimpleNamespace(data=[new_row])

    fake_supabase.rpc_handlers["xera_link_external_wallet"] = handler


def test_start_link_then_verify_and_link_succeeds_with_a_valid_bnb_signature(fake_supabase):
    _install_link_wallet_rpc(fake_supabase)
    _install_consume_nonce_rpc(fake_supabase)
    from xera.chain.wallet_link import start_link, verify_and_link

    acct = Account.create()
    user_id = 42

    started = start_link(user_id, "BNB", acct.address)
    nonce = started["nonce"]

    message = bnb_verify.build_link_message(nonce, acct.address)
    signature = acct.sign_message(encode_defunct(text=message)).signature.hex()

    linked = verify_and_link(user_id, "BNB", acct.address, nonce, signature=signature)
    assert linked["status"] == "VERIFIED"
    assert linked["address"] == acct.address


def test_verify_and_link_rejects_an_invalid_signature(fake_supabase):
    _install_link_wallet_rpc(fake_supabase)
    _install_consume_nonce_rpc(fake_supabase)
    from xera.chain.wallet_link import start_link, verify_and_link, WalletLinkError

    acct = Account.create()
    other = Account.create()
    user_id = 7

    started = start_link(user_id, "BNB", acct.address)
    message = bnb_verify.build_link_message(started["nonce"], acct.address)
    wrong_signature = other.sign_message(encode_defunct(text=message)).signature.hex()

    try:
        verify_and_link(user_id, "BNB", acct.address, started["nonce"], signature=wrong_signature)
        assert False, "expected WalletLinkError"
    except WalletLinkError as e:
        assert str(e) == "invalid_signature"


def test_verify_and_link_rejects_a_reused_nonce(fake_supabase):
    _install_link_wallet_rpc(fake_supabase)
    _install_consume_nonce_rpc(fake_supabase)
    from xera.chain.wallet_link import start_link, verify_and_link, WalletLinkError

    acct = Account.create()
    user_id = 9
    started = start_link(user_id, "BNB", acct.address)
    message = bnb_verify.build_link_message(started["nonce"], acct.address)
    signature = acct.sign_message(encode_defunct(text=message)).signature.hex()

    verify_and_link(user_id, "BNB", acct.address, started["nonce"], signature=signature)

    try:
        verify_and_link(user_id, "BNB", acct.address, started["nonce"], signature=signature)
        assert False, "expected WalletLinkError on nonce reuse"
    except WalletLinkError as e:
        # Distinct from nonce_not_found: the atomic consume RPC can tell
        # "this nonce was already used" apart from "no such nonce", which
        # the old SELECT-then-UPDATE implementation could not.
        assert str(e) == "nonce_already_consumed"


def test_wallet_change_cooldown_blocks_a_second_link_too_soon(fake_supabase):
    _install_link_wallet_rpc(fake_supabase)
    _install_consume_nonce_rpc(fake_supabase)
    from xera.chain.wallet_link import start_link, verify_and_link, WalletLinkError

    acct = Account.create()
    second_acct = Account.create()
    user_id = 11

    started = start_link(user_id, "BNB", acct.address)
    message = bnb_verify.build_link_message(started["nonce"], acct.address)
    signature = acct.sign_message(encode_defunct(text=message)).signature.hex()
    verify_and_link(user_id, "BNB", acct.address, started["nonce"], signature=signature)

    started2 = start_link(user_id, "BNB", second_acct.address)
    message2 = bnb_verify.build_link_message(started2["nonce"], second_acct.address)
    signature2 = second_acct.sign_message(encode_defunct(text=message2)).signature.hex()

    try:
        verify_and_link(user_id, "BNB", second_acct.address, started2["nonce"], signature=signature2)
        assert False, "expected cooldown to block immediate wallet replacement"
    except WalletLinkError as e:
        assert str(e) == "wallet_change_cooldown_active"
