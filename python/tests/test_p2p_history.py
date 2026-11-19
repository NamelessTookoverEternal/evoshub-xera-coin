"""My-transfers view: each row is seen from the caller's side, with the other person's full XERA ID, and leaks nothing else."""
from xera.p2p import _shape_history_row

T = {"id": 5, "sender_user_id": 1, "recipient_user_id": 2, "sender_xera_id": "XR-AAAAAAAA", "recipient_xera_id": "XR-BBBBBBBB",
     "amount": "10.0000", "fee_amount": "0.1000", "status": "COMPLETED", "created_at": "2026-11-19T10:00:00Z",
     "ip_address": "1.2.3.4", "sender_verified": True}
NAMES = {1: "Kofi Mensah", 2: "Ama Boateng"}


def test_sender_sees_recipient_id_and_fee():
    r = _shape_history_row(T, 1, NAMES)
    assert r["direction"] == "sent" and r["counterparty_xera_id"] == "XR-BBBBBBBB"
    assert r["fee_amount"] == "0.1000" and r["counterparty_name"].startswith("A") and "Boateng" not in r["counterparty_name"]


def test_recipient_sees_sender_id_and_no_fee():
    r = _shape_history_row(T, 2, NAMES)
    assert r["direction"] == "received" and r["counterparty_xera_id"] == "XR-AAAAAAAA"
    assert r["fee_amount"] == 0


def test_nothing_private_leaks():
    r = _shape_history_row(T, 2, NAMES)
    assert set(r) == {"id", "direction", "counterparty_xera_id", "counterparty_name", "amount", "fee_amount", "status", "created_at"}
    assert "Mensah" not in r["counterparty_name"]
