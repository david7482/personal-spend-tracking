import base64
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

from spend_tracking.domains.models import LineMessage
from spend_tracking.interfaces.line_message_queue import LineMessageQueue
from spend_tracking.interfaces.line_message_repository import LineMessageRepository

logger = logging.getLogger(__name__)


class ReceiveLineWebhook:
    def __init__(
        self,
        channel_secret: str,
        repository: LineMessageRepository,
        queue: LineMessageQueue,
    ) -> None:
        self._channel_secret = channel_secret
        self._repository = repository
        self._queue = queue

    def execute(self, body: str, signature: str) -> dict:
        if not self._verify_signature(body, signature):
            logger.warning("Invalid LINE webhook signature")
            return {"statusCode": 401, "body": "Invalid signature"}

        payload = json.loads(body)
        events = payload.get("events", [])

        for event in events:
            if event.get("type") != "message":
                logger.info(
                    "Skipping non-message event",
                    extra={"type": event.get("type")},
                )
                continue

            message_obj = event.get("message", {})
            message_type = message_obj.get("type", "unknown")
            message_text = message_obj.get("text") if message_type == "text" else None

            line_message = LineMessage(
                id=None,
                line_user_id=event["source"]["userId"],
                message_type=message_type,
                message=message_text,
                reply_token=event.get("replyToken"),
                raw_event=event,
                timestamp=datetime.fromtimestamp(event["timestamp"] / 1000, tz=UTC),
                created_at=datetime.now(UTC),
            )

            self._repository.save_line_message(line_message)
            logger.info(
                "Saved LINE message",
                extra={
                    "line_message_id": line_message.id,
                    "line_user_id": line_message.line_user_id,
                    "message_type": message_type,
                },
            )

            self._queue.send_message({"line_message_id": line_message.id})

        return {"statusCode": 200, "body": "OK"}

    def _verify_signature(self, body: str, signature: str) -> bool:
        expected = base64.b64encode(
            hmac.new(
                self._channel_secret.encode("utf-8"),
                body.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return hmac.compare_digest(expected, signature)
