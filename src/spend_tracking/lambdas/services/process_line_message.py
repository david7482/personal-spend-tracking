import json
import logging
from datetime import UTC, datetime

import psycopg2
from anthropic import Anthropic, beta_tool

from spend_tracking.domains.models import ChatMessage
from spend_tracking.interfaces.chat_message_repository import ChatMessageRepository

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a personal finance assistant. You help the user understand their spending \
by querying their transaction database and performing calculations.

Always respond in the same language the user writes in.

You have access to:
- query_db: Run read-only SQL against the transactions table. Columns: id, source_type, \
source_id, bank, transaction_at, region, amount, currency, merchant, category, notes, \
raw_data, created_at.
- code_execution: Run Python/bash code for calculations, data analysis, and visualizations.

Guidelines:
- Keep responses concise (this is a chat app, not a report).
- Use query_db to look up real transaction data before answering spending questions.
- Use code_execution for calculations, aggregations, or formatting that SQL alone can't do.
- Amounts are stored as DECIMAL. Currency is a string like 'TWD', 'USD'.
- When showing monetary values, include the currency symbol.
- If the user's question is unclear, ask for clarification.\
"""

FALLBACK_MESSAGE = "Sorry, I'm having trouble right now. Please try again later."


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


def _validate_sql(sql: str) -> bool:
    """Only allow SELECT statements."""
    stripped = sql.strip().upper()
    return stripped.startswith("SELECT") or stripped.startswith("WITH")


def _build_messages(
    history: list[ChatMessage], current: ChatMessage
) -> list[dict]:
    """Build Anthropic messages array from conversation history."""
    messages: list[dict] = []
    for msg in history:
        if msg.content is not None:
            messages.append({"role": msg.role, "content": msg.content})
    if current.content is not None:
        messages.append({"role": "user", "content": current.content})
    return messages


def _extract_text(message: object) -> str:
    """Extract text content from Anthropic response message."""
    parts: list[str] = []
    for block in message.content:  # type: ignore[attr-defined]
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts) if parts else FALLBACK_MESSAGE


def _make_query_db_tool(connection_string: str):  # type: ignore[no-untyped-def]
    """Create a query_db beta_tool function bound to a DB connection string."""

    @beta_tool
    def query_db(sql: str) -> str:
        """Run a read-only SQL query against the transactions table.
        Only SELECT statements are allowed. The transactions table has columns:
        id, source_type, source_id, bank, transaction_at, region, amount,
        currency, merchant, category, notes, raw_data, created_at.

        Args:
            sql: A SELECT SQL query to run against the transactions table.
        Returns:
            JSON array of result rows, or an error message.
        """
        if not _validate_sql(sql):
            return json.dumps({"error": "Only SELECT queries are allowed."})

        try:
            with psycopg2.connect(connection_string) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    columns = [desc[0] for desc in cur.description or []]
                    rows = cur.fetchall()
                    result = [dict(zip(columns, row)) for row in rows]
                    return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    return query_db


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
            query_db_tool = _make_query_db_tool(self._db_connection_string)
            runner = self._client.beta.messages.tool_runner(
                model=self._model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=[
                    query_db_tool,
                    {"type": "code_execution_20260120", "name": "code_execution"},
                ],
                messages=messages,
            )
            final_message = None
            for message in runner:
                final_message = message
            reply_text = _extract_text(final_message) if final_message else FALLBACK_MESSAGE
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
                    "input_tokens": getattr(message.usage, "input_tokens", None),  # type: ignore[union-attr]
                    "output_tokens": getattr(message.usage, "output_tokens", None),  # type: ignore[union-attr]
                },
            }
        except Exception:
            return None
