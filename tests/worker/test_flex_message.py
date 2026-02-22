from datetime import UTC, datetime
from decimal import Decimal

from spend_tracking.shared.domain.models import Transaction


def _make_transaction(
    merchant: str | None = "Test Store",
    amount: Decimal = Decimal("1250"),
    currency: str = "TWD",
    category: str | None = "Food",
    transaction_at: datetime | None = None,
) -> Transaction:
    return Transaction(
        id=1,
        source_type="email",
        source_id=1,
        bank="cathay",
        transaction_at=transaction_at or datetime(2026, 2, 22, 15, 40, tzinfo=UTC),
        region="TW",
        amount=amount,
        currency=currency,
        merchant=merchant,
        category=category,
        notes=None,
        raw_data=None,
        created_at=datetime(2026, 2, 22, 15, 40, tzinfo=UTC),
    )


def test_build_flex_message_single_transaction():
    from spend_tracking.worker.services.flex_message import build_flex_message

    txn = _make_transaction()
    result = build_flex_message("cathay", [txn])

    assert result["type"] == "bubble"
    assert result["size"] == "mega"

    # Header: bank name + transaction count
    header_texts = [c["text"] for c in result["header"]["contents"]]
    assert header_texts[0] == "cathay"
    assert "1" in header_texts[1]

    # Body: one transaction row
    body_contents = result["body"]["contents"]
    # Should have one transaction box (no separator for single txn)
    assert len(body_contents) == 1
    row = body_contents[0]
    # Left side: merchant + metadata
    merchant_text = row["contents"][0]["contents"][0]["text"]
    assert "Test Store" in merchant_text
    # Right side: amount
    amount_text = row["contents"][1]["text"]
    assert "1,250" in amount_text

    # Footer: total
    footer_texts = [c["text"] for c in result["footer"]["contents"]]
    assert "1,250" in footer_texts[1]


def test_build_flex_message_multiple_transactions():
    from spend_tracking.worker.services.flex_message import build_flex_message

    txns = [
        _make_transaction(
            merchant="Starbucks", amount=Decimal("1250"), category="Food"
        ),
        _make_transaction(merchant="IKEA", amount=Decimal("3500"), category="Shopping"),
    ]
    result = build_flex_message("cathay", txns)

    header_texts = [c["text"] for c in result["header"]["contents"]]
    assert "2" in header_texts[1]

    # Body: txn1 + separator + txn2
    body_contents = result["body"]["contents"]
    assert len(body_contents) == 3
    assert body_contents[1]["type"] == "separator"

    # Footer total should sum both
    footer_total = result["footer"]["contents"][1]["text"]
    assert "4,750" in footer_total


def test_build_flex_message_nil_merchant_and_category():
    from spend_tracking.worker.services.flex_message import build_flex_message

    txn = _make_transaction(merchant=None, category=None)
    result = build_flex_message("cathay", [txn])

    row = result["body"]["contents"][0]
    merchant_text = row["contents"][0]["contents"][0]["text"]
    assert merchant_text == "-"

    metadata_text = row["contents"][0]["contents"][1]["text"]
    # Should still have the date, no category prefix
    assert "02/22" in metadata_text


def test_build_flex_message_formats_amount_with_commas():
    from spend_tracking.worker.services.flex_message import build_flex_message

    txn = _make_transaction(amount=Decimal("12345678"))
    result = build_flex_message("cathay", [txn])

    row = result["body"]["contents"][0]
    amount_text = row["contents"][1]["text"]
    assert "NT$12,345,678" in amount_text
