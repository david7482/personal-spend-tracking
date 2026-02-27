import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from spend_tracking.domains.models import ChatMessage

SYSTEM_PROMPT = "You are a personal finance assistant."


def _make_user_message(msg_id: int = 42, content: str = "Hello") -> ChatMessage:
    return ChatMessage(
        id=msg_id,
        line_user_id="U123",
        role="user",
        content=content,
        message_type="text",
        raw_event={"type": "message"},
        timestamp=datetime(2026, 2, 27, 10, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 2, 27, 10, 0, 1, tzinfo=UTC),
    )


def _make_history() -> list[ChatMessage]:
    return [
        ChatMessage(
            id=1,
            line_user_id="U123",
            role="user",
            content="How much did I spend?",
            message_type="text",
            raw_event=None,
            timestamp=datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC),
            created_at=datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC),
        ),
        ChatMessage(
            id=2,
            line_user_id="U123",
            role="assistant",
            content="You spent $100.",
            message_type="text",
            raw_event=None,
            timestamp=datetime(2026, 2, 27, 9, 0, 1, tzinfo=UTC),
            created_at=datetime(2026, 2, 27, 9, 0, 1, tzinfo=UTC),
        ),
    ]


def test_execute_loads_message_runs_agent_saves_and_pushes():
    from spend_tracking.lambdas.services.process_line_message import (
        ProcessLineMessage,
    )

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = _make_user_message()
    mock_repo.load_history.return_value = _make_history()

    mock_final_message = MagicMock()
    mock_final_message.content = [MagicMock(type="text", text="Agent reply")]
    mock_final_message.model = "claude-opus-4-6"
    mock_final_message.stop_reason = "end_turn"
    mock_final_message.usage = MagicMock(
        input_tokens=100, output_tokens=50
    )

    mock_runner = MagicMock()
    mock_runner.__iter__ = MagicMock(
        return_value=iter([mock_final_message])
    )

    mock_client = MagicMock()
    mock_client.beta.messages.tool_runner.return_value = mock_runner

    mock_push = MagicMock()

    service = ProcessLineMessage(
        client=mock_client,
        model="claude-opus-4-6",
        chat_message_repository=mock_repo,
        line_push_sender=mock_push,
        db_connection_string="postgresql://fake",
    )
    service.execute(chat_message_id=42)

    mock_repo.get_by_id.assert_called_once_with(42)
    mock_repo.load_history.assert_called_once_with("U123", limit=20)
    mock_client.beta.messages.tool_runner.assert_called_once()
    mock_repo.save.assert_called_once()
    saved = mock_repo.save.call_args[0][0]
    assert saved.role == "assistant"
    assert saved.content == "Agent reply"
    mock_push.send_text.assert_called_once_with("U123", "Agent reply")


def test_execute_handles_api_error_sends_fallback():
    from spend_tracking.lambdas.services.process_line_message import (
        ProcessLineMessage,
    )

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = _make_user_message()
    mock_repo.load_history.return_value = []

    mock_runner = MagicMock()
    mock_runner.__iter__ = MagicMock(side_effect=Exception("API error"))

    mock_client = MagicMock()
    mock_client.beta.messages.tool_runner.return_value = mock_runner

    mock_push = MagicMock()

    service = ProcessLineMessage(
        client=mock_client,
        model="claude-opus-4-6",
        chat_message_repository=mock_repo,
        line_push_sender=mock_push,
        db_connection_string="postgresql://fake",
    )
    service.execute(chat_message_id=42)

    mock_push.send_text.assert_called_once()
    fallback_text = mock_push.send_text.call_args[0][1]
    assert "try again" in fallback_text.lower() or "trouble" in fallback_text.lower()


def test_query_db_rejects_non_select():
    from spend_tracking.lambdas.services.process_line_message import (
        _validate_sql,
    )

    assert _validate_sql("SELECT * FROM transactions") is True
    assert _validate_sql("select count(*) from transactions") is True
    assert _validate_sql("WITH cte AS (SELECT 1) SELECT * FROM cte") is True
    assert _validate_sql("DROP TABLE transactions") is False
    assert _validate_sql("DELETE FROM transactions") is False
    assert _validate_sql("INSERT INTO transactions VALUES (1)") is False
    assert _validate_sql("UPDATE transactions SET amount = 0") is False


def test_build_messages_from_history():
    from spend_tracking.lambdas.services.process_line_message import (
        _build_messages,
    )

    history = _make_history()
    current = _make_user_message(content="New question")
    messages = _build_messages(history, current)

    assert len(messages) == 3
    assert messages[0] == {"role": "user", "content": "How much did I spend?"}
    assert messages[1] == {"role": "assistant", "content": "You spent $100."}
    assert messages[2] == {"role": "user", "content": "New question"}
