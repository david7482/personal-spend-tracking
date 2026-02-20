from datetime import datetime, timezone
from unittest.mock import MagicMock


def _make_raw_headers(to_address: str, from_address: str = "sender@example.com") -> bytes:
    return (
        f"From: {from_address}\r\n"
        f"To: {to_address}\r\n"
        f"Subject: Test\r\n"
        f"Date: Sat, 21 Feb 2026 10:00:00 +0000\r\n"
        f"\r\n"
    ).encode()


def test_enqueues_for_active_registered_address():
    from spend_tracking.router.services.validate_and_enqueue import ValidateAndEnqueue
    from spend_tracking.shared.domain.models import RegisteredAddress

    storage = MagicMock()
    repository = MagicMock()
    queue = MagicMock()

    to_addr = "bank-abc123@mail.david74.dev"
    storage.get_email_headers.return_value = _make_raw_headers(to_addr)
    repository.get_registered_address.return_value = RegisteredAddress(
        id=1,
        address=to_addr,
        prefix="bank",
        label="Test",
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    service = ValidateAndEnqueue(storage, repository, queue)
    result = service.execute("some-s3-key")

    assert result is True
    queue.send_message.assert_called_once()
    msg = queue.send_message.call_args[0][0]
    assert msg["s3_key"] == "some-s3-key"
    assert msg["address"] == to_addr
    assert msg["sender"] == "sender@example.com"


def test_skips_unregistered_address():
    from spend_tracking.router.services.validate_and_enqueue import ValidateAndEnqueue

    storage = MagicMock()
    repository = MagicMock()
    queue = MagicMock()

    storage.get_email_headers.return_value = _make_raw_headers("unknown@mail.david74.dev")
    repository.get_registered_address.return_value = None

    service = ValidateAndEnqueue(storage, repository, queue)
    result = service.execute("some-s3-key")

    assert result is False
    queue.send_message.assert_not_called()


def test_skips_inactive_address():
    from spend_tracking.router.services.validate_and_enqueue import ValidateAndEnqueue
    from spend_tracking.shared.domain.models import RegisteredAddress

    storage = MagicMock()
    repository = MagicMock()
    queue = MagicMock()

    to_addr = "bank-abc123@mail.david74.dev"
    storage.get_email_headers.return_value = _make_raw_headers(to_addr)
    repository.get_registered_address.return_value = RegisteredAddress(
        id=2,
        address=to_addr,
        prefix="bank",
        label="Test",
        is_active=False,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    service = ValidateAndEnqueue(storage, repository, queue)
    result = service.execute("some-s3-key")

    assert result is False
    queue.send_message.assert_not_called()


def test_checks_delivered_to_header():
    from spend_tracking.router.services.validate_and_enqueue import ValidateAndEnqueue
    from spend_tracking.shared.domain.models import RegisteredAddress

    storage = MagicMock()
    repository = MagicMock()
    queue = MagicMock()

    target_addr = "bank-abc123@mail.david74.dev"
    raw = (
        "From: sender@example.com\r\n"
        "To: someother@example.com\r\n"
        f"Delivered-To: {target_addr}\r\n"
        "Subject: Test\r\n"
        "Date: Sat, 21 Feb 2026 10:00:00 +0000\r\n"
        "\r\n"
    ).encode()
    storage.get_email_headers.return_value = raw

    def lookup(addr):
        if addr == target_addr:
            return RegisteredAddress(
                id=3,
                address=target_addr,
                prefix="bank",
                label="Test",
                is_active=True,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        return None

    repository.get_registered_address.side_effect = lookup

    service = ValidateAndEnqueue(storage, repository, queue)
    result = service.execute("s3-key")

    assert result is True
    msg = queue.send_message.call_args[0][0]
    assert msg["address"] == target_addr
