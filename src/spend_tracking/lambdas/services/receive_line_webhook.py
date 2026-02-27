import base64
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from spend_tracking.domains.models import ChatMessage
from spend_tracking.interfaces.chat_message_repository import ChatMessageRepository
from spend_tracking.interfaces.line_message_queue import LineMessageQueue

logger = logging.getLogger(__name__)

LINE_LOADING_URL = "https://api.line.me/v2/bot/chat/loading/start"


class ReceiveLineWebhook:
    def __init__(
        self,
        channel_secret: str,
        channel_access_token: str,
        repository: ChatMessageRepository,
        queue: LineMessageQueue,
    ) -> None:
        self._channel_secret = channel_secret
        self._channel_access_token = channel_access_token
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
            line_user_id = event["source"]["userId"]

            chat_message = ChatMessage(
                id=None,
                line_user_id=line_user_id,
                role="user",
                content=message_text,
                message_type=message_type,
                raw_event=event,
                timestamp=datetime.fromtimestamp(event["timestamp"] / 1000, tz=UTC),
                created_at=datetime.now(UTC),
            )

            self._repository.save(chat_message)
            logger.info(
                "Saved chat message",
                extra={
                    "chat_message_id": chat_message.id,
                    "line_user_id": line_user_id,
                    "message_type": message_type,
                },
            )

            self._send_loading_animation(line_user_id)
            self._queue.send_message({"chat_message_id": chat_message.id})

        return {"statusCode": 200, "body": "OK"}

    def _send_loading_animation(self, line_user_id: str) -> None:
        try:
            data = json.dumps({"chatId": line_user_id}).encode("utf-8")
            request = Request(
                LINE_LOADING_URL,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._channel_access_token}",
                },
            )
            with urlopen(request):
                pass
        except Exception:
            logger.exception(
                "Failed to send loading animation",
                extra={"line_user_id": line_user_id},
            )

    def _verify_signature(self, body: str, signature: str) -> bool:
        expected = base64.b64encode(
            hmac.new(
                self._channel_secret.encode("utf-8"),
                body.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return hmac.compare_digest(expected, signature)
