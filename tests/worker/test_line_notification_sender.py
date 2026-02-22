import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from spend_tracking.shared.domain.models import Transaction


def _make_transaction(
    merchant: str = "星巴克",
    amount: Decimal = Decimal("1250"),
) -> Transaction:
    return Transaction(
        id=1,
        source_type="email",
        source_id=1,
        bank="cathay",
        transaction_at=datetime(2026, 2, 22, 15, 40, tzinfo=UTC),
        region="TW",
        amount=amount,
        currency="TWD",
        merchant=merchant,
        category="餐飲",
        notes=None,
        raw_data=None,
        created_at=datetime(2026, 2, 22, 15, 40, tzinfo=UTC),
    )


@patch("spend_tracking.shared.adapters.notification_sender_line.urlopen")
def test_sends_push_message_to_line_api(mock_urlopen):
    from spend_tracking.shared.adapters.notification_sender_line import (
        LineNotificationSender,
    )

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b'{"message":"ok"}'
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    sender = LineNotificationSender(channel_access_token="test-token")
    sender.send_transaction_notification(
        recipient_id="U1234567890",
        bank="cathay",
        transactions=[_make_transaction()],
    )

    mock_urlopen.assert_called_once()
    request = mock_urlopen.call_args[0][0]
    assert request.full_url == "https://api.line.me/v2/bot/message/push"
    assert request.get_header("Authorization") == "Bearer test-token"
    assert request.get_header("Content-type") == "application/json"

    body = json.loads(request.data)
    assert body["to"] == "U1234567890"
    assert len(body["messages"]) == 1
    assert body["messages"][0]["type"] == "flex"
    assert "cathay" in body["messages"][0]["altText"]


@patch("spend_tracking.shared.adapters.notification_sender_line.urlopen")
def test_logs_error_on_http_failure(mock_urlopen, caplog):
    from spend_tracking.shared.adapters.notification_sender_line import (
        LineNotificationSender,
    )

    mock_urlopen.side_effect = Exception("Connection refused")

    sender = LineNotificationSender(channel_access_token="test-token")
    # Should NOT raise
    sender.send_transaction_notification(
        recipient_id="U1234567890",
        bank="cathay",
        transactions=[_make_transaction()],
    )

    assert "LINE notification failed" in caplog.text
