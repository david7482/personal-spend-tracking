import base64
import hashlib
import hmac
import json
from unittest.mock import MagicMock, call

CHANNEL_SECRET = "test-channel-secret"
LINE_CHANNEL_ACCESS_TOKEN = "test-token"


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
    timestamp: int = 1740646800000,
) -> str:
    return json.dumps(
        {
            "events": [
                {
                    "type": "message",
                    "replyToken": "reply-token-abc",
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

    repository.save.side_effect = set_id

    body = _make_webhook_body()
    signature = _sign(body)

    service = ReceiveLineWebhook(
        CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, repository, queue
    )
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    repository.save.assert_called_once()
    saved = repository.save.call_args[0][0]
    assert saved.line_user_id == "U1234567890abcdef"
    assert saved.role == "user"
    assert saved.message_type == "text"
    assert saved.content == "Hello"
    assert saved.raw_event["type"] == "message"

    queue.send_message.assert_called_once()
    enqueued = queue.send_message.call_args[0][0]
    assert enqueued["chat_message_id"] == 42


def test_loading_animation_is_sent(monkeypatch):
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    def set_id(msg):
        msg.id = 42

    repository.save.side_effect = set_id

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__ = MagicMock()
    mock_urlopen.__exit__ = MagicMock(return_value=False)
    mock_urlopen_fn = MagicMock(return_value=mock_urlopen)
    monkeypatch.setattr(
        "spend_tracking.lambdas.services.receive_line_webhook.urlopen",
        mock_urlopen_fn,
    )

    body = _make_webhook_body()
    signature = _sign(body)

    service = ReceiveLineWebhook(
        CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, repository, queue
    )
    service.execute(body, signature)

    mock_urlopen_fn.assert_called_once()
    request = mock_urlopen_fn.call_args[0][0]
    assert "loading/start" in request.full_url
    payload = json.loads(request.data)
    assert payload["chatId"] == "U1234567890abcdef"


def test_invalid_signature_returns_401():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    body = _make_webhook_body()
    bad_signature = "invalid-signature"

    service = ReceiveLineWebhook(
        CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, repository, queue
    )
    result = service.execute(body, bad_signature)

    assert result["statusCode"] == 401
    repository.save.assert_not_called()
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

    service = ReceiveLineWebhook(
        CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, repository, queue
    )
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    repository.save.assert_not_called()
    queue.send_message.assert_not_called()


def test_non_text_message_saves_with_null_content():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    def set_id(msg):
        msg.id = 99

    repository.save.side_effect = set_id

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

    service = ReceiveLineWebhook(
        CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, repository, queue
    )
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    saved = repository.save.call_args[0][0]
    assert saved.message_type == "sticker"
    assert saved.content is None
