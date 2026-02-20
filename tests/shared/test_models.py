from datetime import datetime, timezone
from uuid import uuid4


def test_registered_address_creation():
    from spend_tracking.shared.domain.models import RegisteredAddress

    addr = RegisteredAddress(
        address="bank-abc123@mail.david74.dev",
        prefix="bank",
        label="Test Bank",
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert addr.address == "bank-abc123@mail.david74.dev"
    assert addr.prefix == "bank"
    assert addr.label == "Test Bank"
    assert addr.is_active is True


def test_registered_address_optional_label():
    from spend_tracking.shared.domain.models import RegisteredAddress

    addr = RegisteredAddress(
        address="card-xyz@mail.david74.dev",
        prefix="card",
        label=None,
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert addr.label is None


def test_email_creation():
    from spend_tracking.shared.domain.models import Email

    email_id = uuid4()
    email = Email(
        id=email_id,
        address="bank-abc123@mail.david74.dev",
        sender="noreply@bank.com",
        subject="Your statement",
        body_html="<p>Statement</p>",
        body_text="Statement",
        raw_s3_key="abc123",
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        parsed_data=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert email.id == email_id
    assert email.sender == "noreply@bank.com"
    assert email.parsed_data is None


def test_email_with_parsed_data():
    from spend_tracking.shared.domain.models import Email

    parsed = {"type": "credit_card_statement", "amount": 12345}
    email = Email(
        id=uuid4(),
        address="bank-abc123@mail.david74.dev",
        sender="noreply@bank.com",
        subject="Statement",
        body_html=None,
        body_text="text",
        raw_s3_key="key1",
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        parsed_data=parsed,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert email.parsed_data["amount"] == 12345
