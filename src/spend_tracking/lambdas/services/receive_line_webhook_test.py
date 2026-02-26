import base64
import hashlib
import hmac
import json
from unittest.mock import MagicMock

CHANNEL_SECRET = "test-channel-secret"


def _sign(body: str, secret: str = CHANNEL_SECRET) -> str:
    return base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")


def _make_webhook_body(
    user_id: str = "U1234567890abcdef",
    message_text: str = "Hello",
    message_type: str = "text",
    reply_token: str = "reply-token-abc",
    timestamp: int = 1740646800000,
) -> str:
    return json.dumps(
        {
            "events": [
                {
                    "type": "message",
                    "replyToken": reply_token,
                    "source": {"type": "user", "userId": user_id},
                    "timestamp": timestamp,
                    "message": {"type": message_type, "text": message_text},
                }
            ]
        }
    )


def test_valid_signature_saves_and_enqueues():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    def set_id(msg):
        msg.id = 42

    repository.save_line_message.side_effect = set_id

    body = _make_webhook_body()
    signature = _sign(body)

    service = ReceiveLineWebhook(CHANNEL_SECRET, repository, queue)
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    repository.save_line_message.assert_called_once()
    saved = repository.save_line_message.call_args[0][0]
    assert saved.line_user_id == "U1234567890abcdef"
    assert saved.message_type == "text"
    assert saved.message == "Hello"
    assert saved.reply_token == "reply-token-abc"
    assert saved.raw_event["type"] == "message"

    queue.send_message.assert_called_once()
    enqueued = queue.send_message.call_args[0][0]
    assert enqueued["line_message_id"] == 42


def test_invalid_signature_returns_401():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    body = _make_webhook_body()
    bad_signature = "invalid-signature"

    service = ReceiveLineWebhook(CHANNEL_SECRET, repository, queue)
    result = service.execute(body, bad_signature)

    assert result["statusCode"] == 401
    repository.save_line_message.assert_not_called()
    queue.send_message.assert_not_called()


def test_non_message_events_are_skipped():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    body = json.dumps(
        {
            "events": [
                {
                    "type": "follow",
                    "source": {"type": "user", "userId": "U123"},
                    "timestamp": 1740646800000,
                }
            ]
        }
    )
    signature = _sign(body)

    service = ReceiveLineWebhook(CHANNEL_SECRET, repository, queue)
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    repository.save_line_message.assert_not_called()
    queue.send_message.assert_not_called()


def test_non_text_message_saves_with_null_message():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    def set_id(msg):
        msg.id = 99

    repository.save_line_message.side_effect = set_id

    body = json.dumps(
        {
            "events": [
                {
                    "type": "message",
                    "replyToken": "token",
                    "source": {"type": "user", "userId": "U123"},
                    "timestamp": 1740646800000,
                    "message": {
                        "type": "sticker",
                        "stickerId": "123",
                        "packageId": "456",
                    },
                }
            ]
        }
    )
    signature = _sign(body)

    service = ReceiveLineWebhook(CHANNEL_SECRET, repository, queue)
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    saved = repository.save_line_message.call_args[0][0]
    assert saved.message_type == "sticker"
    assert saved.message is None
