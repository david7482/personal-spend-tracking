import json
import logging
from datetime import UTC, datetime

from anthropic import Anthropic

from spend_tracking.domains.models import ChatMessage
from spend_tracking.interfaces.chat_message_repository import ChatMessageRepository
from spend_tracking.lambdas.services.agent import (
    FALLBACK_MESSAGE,
    build_tools,
    extract_text,
    run_agent,
)

logger = logging.getLogger(__name__)


class LinePushSender:
    """Sends text messages via LINE Push API."""

    def __init__(self, channel_access_token: str) -> None:
        self._token = channel_access_token

    def send_text(self, line_user_id: str, text: str) -> None:
        from urllib.request import Request, urlopen

        payload = {
            "to": line_user_id,
            "messages": [{"type": "text", "text": text}],
        }
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            "https://api.line.me/v2/bot/message/push",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._token}",
            },
        )
        with urlopen(request) as response:
            logger.info(
                "LINE push sent",
                extra={"line_user_id": line_user_id, "status": response.status},
            )


def _build_messages(history: list[ChatMessage], current: ChatMessage) -> list[dict]:
    """Build Anthropic messages array from conversation history."""
    messages: list[dict] = []
    for msg in history:
        if msg.content is not None:
            messages.append({"role": msg.role, "content": msg.content})
    if current.content is not None:
        messages.append({"role": "user", "content": current.content})
    return messages


class ProcessLineMessage:
    def __init__(
        self,
        client: Anthropic,
        model: str,
        chat_message_repository: ChatMessageRepository,
        line_push_sender: LinePushSender,
        db_connection_string: str,
    ) -> None:
        self._client = client
        self._model = model
        self._repo = chat_message_repository
        self._push = line_push_sender
        self._db_connection_string = db_connection_string

    def execute(self, chat_message_id: int) -> None:
        user_msg = self._repo.get_by_id(chat_message_id)
        if user_msg is None:
            logger.error(
                "Chat message not found",
                extra={"chat_message_id": chat_message_id},
            )
            return

        history = self._repo.load_history(user_msg.line_user_id, limit=20)
        messages = _build_messages(history, user_msg)

        if not messages:
            logger.warning(
                "No messages to process",
                extra={"chat_message_id": chat_message_id},
            )
            return

        try:
            tools = build_tools(self._db_connection_string)
            final_message = None
            for message in run_agent(self._client, self._model, tools, messages):
                final_message = message
            reply_text = (
                extract_text(final_message) if final_message else FALLBACK_MESSAGE
            )
        except Exception:
            logger.exception(
                "Agent loop failed",
                extra={"chat_message_id": chat_message_id},
            )
            reply_text = FALLBACK_MESSAGE
            final_message = None

        assistant_msg = ChatMessage(
            id=None,
            line_user_id=user_msg.line_user_id,
            role="assistant",
            content=reply_text,
            message_type="text",
            raw_event=self._extract_metadata(final_message),
            timestamp=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        self._repo.save(assistant_msg)

        self._push.send_text(user_msg.line_user_id, reply_text)

        logger.info(
            "Processed LINE message",
            extra={
                "chat_message_id": chat_message_id,
                "assistant_message_id": assistant_msg.id,
                "reply_length": len(reply_text),
            },
        )

    def _extract_metadata(self, message: object | None) -> dict | None:
        if message is None:
            return None
        try:
            return {
                "model": getattr(message, "model", None),
                "stop_reason": getattr(message, "stop_reason", None),
                "usage": {
                    "input_tokens": getattr(message.usage, "input_tokens", None),  # type: ignore[attr-defined]
                    "output_tokens": getattr(message.usage, "output_tokens", None),  # type: ignore[attr-defined]
                },
            }
        except Exception:
            return None
