"""
Website Creation orders: prices, the XERA saving, file sniffing, and the
confirm-before-paid rules. The DB helpers are replaced by an in-memory row;
Paystack / NOWPayments HTTP is never called.
"""
import asyncio

import pytest

from services import website_orders as wo


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------- pricing

def test_starter_is_400_down_from_800_with_10pct_xera():
    p = wo.package_pricing("starter")
    assert p["list_price"] == 800 and p["price"] == 400
    assert p["percent_off"] == 50
    assert p["xera_percent"] == 10 and p["xera_saving"] == 40.0 and p["price_with_xera"] == 360.0


def test_other_packages_keep_their_price_and_custom_is_quote_only():
    assert wo.package_pricing("business")["price"] == 1100
    assert wo.package_pricing("premium")["price"] == 2500
    assert wo.package_pricing("business")["percent_off"] == 50
    assert wo.package_pricing("whatsapp_bot")["percent_off"] == 50
    assert wo.package_pricing("custom") is None


def test_xera_percent_is_configurable_and_clamped(monkeypatch):
    monkeypatch.setenv("WEBSITE_XERA_DISCOUNT_PCT", "5")
    assert wo.package_pricing("starter")["xera_saving"] == 20.0
    monkeypatch.setenv("WEBSITE_XERA_DISCOUNT_PCT", "garbage")
    assert wo.package_pricing("starter")["xera_saving"] == 40.0


# ---------------------------------------------------------------- uploads

@pytest.mark.parametrize("head,expected", [
    (b"\x89PNG\r\n\x1a\n" + b"x" * 8, "image/png"),
    (b"\xff\xd8\xff\xe0" + b"x" * 12, "image/jpeg"),
    (b"GIF89a" + b"x" * 10, "image/gif"),
    (b"%PDF-1.7" + b"x" * 8, "application/pdf"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
])
def test_sniff_accepts_real_images_and_pdf(head, expected):
    assert wo.sniff_file_type(head)[0] == expected


@pytest.mark.parametrize("head", [b"<svg xmlns", b"<script>alert", b"MZ\x90\x00", b"PK\x03\x04", b""])
def test_sniff_rejects_everything_else(head):
    assert wo.sniff_file_type(head) is None


def test_upload_rejects_oversize_and_bad_type_before_touching_storage(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("storage must not be touched")
    monkeypatch.setattr(wo, "upload_website_file", boom)
    monkeypatch.setattr(wo, "count_website_files", lambda rid: _async(0))

    with pytest.raises(wo.WebsiteOrderError) as e:
        run(wo.save_upload("r1", "big.png", b"\x89PNG\r\n\x1a\n" + b"0" * wo.MAX_FILE_BYTES))
    assert e.value.code == "file_too_large"
    with pytest.raises(wo.WebsiteOrderError) as e:
        run(wo.save_upload("r1", "evil.svg", b"<svg onload=alert(1)>"))
    assert e.value.code == "file_type"


def test_upload_enforces_file_count_cap(monkeypatch):
    monkeypatch.setattr(wo, "count_website_files", lambda rid: _async(wo.MAX_FILES))
    with pytest.raises(wo.WebsiteOrderError) as e:
        run(wo.save_upload("r1", "a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32))
    assert e.value.code == "too_many_files"


# ---------------------------------------------------------------- confirm

async def _async(v):
    return v


class FakeDB:
    def __init__(self, row):
        self.row = row
        self.patches = []

    async def get(self, *, request_id=None, payment_reference=None):
        if payment_reference and self.row.get("payment_reference") == payment_reference:
            return dict(self.row)
        if request_id == self.row["id"]:
            return dict(self.row)
        return None

    async def patch(self, request_id, fields, *, only_if=None):
        self.patches.append(fields)
        if only_if and only_if.get("payment_status") == "neq.paid" and self.row["payment_status"] == "paid":
            return None
        if only_if and only_if.get("payment_status") == "eq.pending" and self.row["payment_status"] != "pending":
            return None
        self.row.update(fields)
        return dict(self.row)


def _row(**over):
    row = {
        "id": "11111111-2222-3333-4444-555555555555", "full_name": "Ama", "email": "ama@example.com",
        "package": "starter", "status": "new", "payment_status": "pending", "payment_method": "paystack",
        "payment_reference": "evos-web-abc", "amount_due_ghs": 360.0, "price_ghs": 400.0,
        "list_price_ghs": 800.0, "xera_discount_ghs": 0, "crypto_usd_cents": None,
    }
    row.update(over)
    return row


@pytest.fixture
def db(monkeypatch):
    d = FakeDB(_row())
    monkeypatch.setattr(wo, "get_website_request", d.get)
    monkeypatch.setattr(wo, "patch_website_request", d.patch)
    monkeypatch.setattr(wo, "_send_paid_emails", lambda row: None)
    return d


def test_paystack_exact_amount_marks_paid_and_issues_receipt(db):
    out = run(wo.confirm_payment("evos-web-abc", amount_minor=36000, currency="GHS"))
    assert out["handled"] and out["receipt_no"].startswith("EVX-WEB-")
    assert db.row["payment_status"] == "paid" and db.row["status"] == "in_review"
    assert wo.build_receipt(db.row)["amount_paid"] == 360.0


def test_wrong_amount_or_currency_is_never_marked_paid(db):
    assert run(wo.confirm_payment("evos-web-abc", amount_minor=100, currency="GHS"))["reason"] == "amount_mismatch"
    assert run(wo.confirm_payment("evos-web-abc", amount_minor=36000, currency="USD"))["reason"] == "amount_mismatch"
    assert db.row["payment_status"] == "pending"


def test_unknown_reference_is_not_handled(db):
    assert run(wo.confirm_payment("evos-web-zzz", amount_minor=36000, currency="GHS"))["reason"] == "unknown_reference"


def test_confirming_twice_is_harmless(db):
    run(wo.confirm_payment("evos-web-abc", amount_minor=36000, currency="GHS"))
    receipt = db.row["receipt_no"]
    again = run(wo.confirm_payment("evos-web-abc", amount_minor=36000, currency="GHS"))
    assert again["already_paid"] and db.row["receipt_no"] == receipt


def test_crypto_compares_stored_usd_cents(monkeypatch):
    d = FakeDB(_row(payment_method="crypto", crypto_usd_cents=2400, payment_reference="evos-web-btc"))
    monkeypatch.setattr(wo, "get_website_request", d.get)
    monkeypatch.setattr(wo, "patch_website_request", d.patch)
    monkeypatch.setattr(wo, "_send_paid_emails", lambda row: None)
    assert run(wo.confirm_payment("evos-web-btc", amount_minor=2300, currency="USD"))["reason"] == "amount_mismatch"
    assert run(wo.confirm_payment("evos-web-btc", amount_minor=2400, currency="USD"))["handled"]


def test_failed_payment_only_flips_a_pending_order(db):
    assert run(wo.mark_payment_failed("evos-web-abc"))["handled"]
    assert db.row["payment_status"] == "failed"
    db.row["payment_status"] = "paid"
    assert run(wo.mark_payment_failed("evos-web-abc"))["handled"] is False
    assert db.row["payment_status"] == "paid"


def test_no_receipt_before_payment():
    with pytest.raises(wo.WebsiteOrderError):
        wo.build_receipt(_row())
