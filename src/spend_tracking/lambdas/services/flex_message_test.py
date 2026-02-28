from datetime import UTC, datetime
from decimal import Decimal

from spend_tracking.domains.models import Transaction


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
    from spend_tracking.lambdas.services.flex_message import build_flex_message

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
    from spend_tracking.lambdas.services.flex_message import build_flex_message

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
    from spend_tracking.lambdas.services.flex_message import build_flex_message

    txn = _make_transaction(merchant=None, category=None)
    result = build_flex_message("cathay", [txn])

    row = result["body"]["contents"][0]
    merchant_text = row["contents"][0]["contents"][0]["text"]
    assert merchant_text == "-"

    metadata_text = row["contents"][0]["contents"][1]["text"]
    # Should still have the date, no category prefix
    assert "02/22" in metadata_text


def test_build_flex_message_formats_amount_with_commas():
    from spend_tracking.lambdas.services.flex_message import build_flex_message

    txn = _make_transaction(amount=Decimal("12345678"))
    result = build_flex_message("cathay", [txn])

    row = result["body"]["contents"][0]
    amount_text = row["contents"][1]["text"]
    assert "NT$12,345,678" in amount_text


def test_build_chat_flex_bubble_key_value_section():
    from spend_tracking.lambdas.services.flex_message import build_chat_flex_bubble

    result = build_chat_flex_bubble(
        title="Monthly Summary",
        sections=[
            {
                "type": "key_value",
                "items": [
                    {"label": "Total", "value": "NT$12,345"},
                    {"label": "Count", "value": "15"},
                ],
            }
        ],
    )

    assert result["type"] == "bubble"
    assert result["size"] == "mega"

    # Header has title
    header_texts = [c["text"] for c in result["header"]["contents"]]
    assert header_texts[0] == "Monthly Summary"

    # Body has key_value rows
    body = result["body"]["contents"]
    assert len(body) == 2  # two k/v rows
    # First row: label on left, value on right
    assert body[0]["contents"][0]["text"] == "Total"
    assert body[0]["contents"][1]["text"] == "NT$12,345"


def test_build_chat_flex_bubble_table_section():
    from spend_tracking.lambdas.services.flex_message import build_chat_flex_bubble

    result = build_chat_flex_bubble(
        title="Top Merchants",
        sections=[
            {
                "type": "table",
                "headers": ["Merchant", "Amount"],
                "rows": [
                    ["7-ELEVEN", "NT$89"],
                    ["Starbucks", "NT$150"],
                ],
            }
        ],
    )

    body = result["body"]["contents"]
    # header row + separator + data row + separator + data row = 5
    assert len(body) == 5
    # Header row is bold
    assert body[0]["contents"][0]["weight"] == "bold"
    # Separators between rows
    assert body[1]["type"] == "separator"
    assert body[3]["type"] == "separator"
    # Data rows
    assert body[2]["contents"][0]["text"] == "7-ELEVEN"
    assert body[2]["contents"][1]["text"] == "NT$89"


def test_build_chat_flex_bubble_unknown_section_type_renders_as_text():
    from spend_tracking.lambdas.services.flex_message import build_chat_flex_bubble

    result = build_chat_flex_bubble(
        title="Summary",
        sections=[
            {
                "type": "summary",
                "items": [
                    {"label": "Total", "value": "NT$5,000"},
                    {"label": "Count", "value": "10"},
                ],
            }
        ],
    )

    body = result["body"]["contents"]
    assert len(body) == 2
    assert body[0]["type"] == "text"
    assert "Total" in body[0]["text"]
    assert "NT$5,000" in body[0]["text"]


def test_build_chat_flex_bubble_empty_sections_produces_valid_contents():
    from spend_tracking.lambdas.services.flex_message import build_chat_flex_bubble

    result = build_chat_flex_bubble(title="Empty", sections=[])

    body = result["body"]["contents"]
    # Must have at least one element (LINE Flex API requirement)
    assert len(body) >= 1


def test_build_chat_flex_bubble_unknown_type_no_items_produces_valid_contents():
    from spend_tracking.lambdas.services.flex_message import build_chat_flex_bubble

    result = build_chat_flex_bubble(
        title="Bad Section",
        sections=[{"type": "unknown"}],
    )

    body = result["body"]["contents"]
    assert len(body) >= 1


def test_build_chat_flex_bubble_mixed_sections():
    from spend_tracking.lambdas.services.flex_message import build_chat_flex_bubble

    result = build_chat_flex_bubble(
        title="February Report",
        sections=[
            {
                "type": "key_value",
                "items": [{"label": "Total", "value": "NT$5,000"}],
            },
            {
                "type": "table",
                "headers": ["Category", "Amount"],
                "rows": [["Food", "NT$3,000"]],
            },
        ],
    )

    body = result["body"]["contents"]
    # 1 kv row + section_separator + header_row + separator + data_row = 5
    assert len(body) == 5
    # First item is key_value
    assert body[0]["contents"][0]["text"] == "Total"
    # Separator between sections
    assert body[1]["type"] == "separator"
