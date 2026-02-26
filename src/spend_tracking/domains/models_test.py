from datetime import UTC, datetime


def test_registered_address_creation():
    from spend_tracking.domains.models import RegisteredAddress

    addr = RegisteredAddress(
        id=1,
        address="bank-abc123@mail.david74.dev",
        prefix="bank",
        label="Test Bank",
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert addr.id == 1
    assert addr.address == "bank-abc123@mail.david74.dev"
    assert addr.prefix == "bank"
    assert addr.label == "Test Bank"
    assert addr.is_active is True


def test_registered_address_optional_label():
    from spend_tracking.domains.models import RegisteredAddress

    addr = RegisteredAddress(
        id=2,
        address="card-xyz@mail.david74.dev",
        prefix="card",
        label=None,
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert addr.label is None


def test_email_creation():
    from spend_tracking.domains.models import Email

    email = Email(
        id=42,
        address="bank-abc123@mail.david74.dev",
        sender="noreply@bank.com",
        subject="Your statement",
        body_text="Statement",
        raw_s3_key="abc123",
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        parsed_data=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert email.id == 42
    assert email.sender == "noreply@bank.com"
    assert email.parsed_data is None


def test_email_with_parsed_data():
    from spend_tracking.domains.models import Email

    parsed = {"type": "credit_card_statement", "amount": 12345}
    email = Email(
        id=None,
        address="bank-abc123@mail.david74.dev",
        sender="noreply@bank.com",
        subject="Statement",
        body_text="text",
        raw_s3_key="key1",
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        parsed_data=parsed,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert email.id is None
    assert email.parsed_data is not None
    assert email.parsed_data["amount"] == 12345


def test_transaction_creation():
    from datetime import datetime
    from decimal import Decimal

    from spend_tracking.domains.models import Transaction

    txn = Transaction(
        id=None,
        source_type="email",
        source_id=42,
        bank="cathay",
        transaction_at=datetime(2026, 2, 19, 15, 40, tzinfo=UTC),
        region="TW",
        amount=Decimal("330.00"),
        currency="TWD",
        merchant="國立臺灣科學教育館",
        category="線上繳費",
        notes=None,
        raw_data={"card_last_four": "6903", "card_type": "正卡"},
        created_at=datetime(2026, 2, 20, 6, 23, tzinfo=UTC),
    )
    assert txn.bank == "cathay"
    assert txn.amount == Decimal("330.00")
    assert txn.merchant == "國立臺灣科學教育館"
    assert txn.raw_data is not None
    assert txn.raw_data["card_type"] == "正卡"
    assert txn.id is None
