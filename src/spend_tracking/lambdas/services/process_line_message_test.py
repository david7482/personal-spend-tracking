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
    mock_final_message.usage = MagicMock(input_tokens=100, output_tokens=50)

    mock_runner = MagicMock()
    mock_runner.__iter__ = MagicMock(return_value=iter([mock_final_message]))

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
    mock_push.send_messages.assert_called_once()
    sent_messages = mock_push.send_messages.call_args[0][1]
    assert len(sent_messages) == 1
    assert sent_messages[0] == {"type": "text", "text": "Agent reply"}


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

    mock_push.send_messages.assert_called_once()
    sent_messages = mock_push.send_messages.call_args[0][1]
    assert len(sent_messages) == 1
    fallback_text = sent_messages[0]["text"]
    assert "try again" in fallback_text.lower() or "trouble" in fallback_text.lower()


def test_query_db_rejects_non_select():
    from spend_tracking.lambdas.services.agent import validate_sql

    assert validate_sql("SELECT * FROM transactions") is True
    assert validate_sql("select count(*) from transactions") is True
    assert validate_sql("WITH cte AS (SELECT 1) SELECT * FROM cte") is True
    assert validate_sql("DROP TABLE transactions") is False
    assert validate_sql("DELETE FROM transactions") is False
    assert validate_sql("INSERT INTO transactions VALUES (1)") is False
    assert validate_sql("UPDATE transactions SET amount = 0") is False


@patch("spend_tracking.lambdas.services.process_line_message.urlopen")
def test_send_messages_posts_multiple_messages(mock_urlopen):
    from spend_tracking.lambdas.services.process_line_message import LinePushSender

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    sender = LinePushSender(channel_access_token="test-token")
    messages: list[dict] = [
        {"type": "flex", "altText": "Summary", "contents": {"type": "bubble"}},
        {"type": "text", "text": "Hello"},
    ]
    sender.send_messages("U123", messages)

    mock_urlopen.assert_called_once()
    request = mock_urlopen.call_args[0][0]
    body = json.loads(request.data)
    assert body["to"] == "U123"
    assert len(body["messages"]) == 2
    assert body["messages"][0]["type"] == "flex"
    assert body["messages"][1]["type"] == "text"


def test_build_tools_returns_tuple_with_flex_bubbles():
    from spend_tracking.lambdas.services.agent import build_tools

    result = build_tools("postgresql://fake")
    assert isinstance(result, tuple)
    assert len(result) == 2
    tools, flex_bubbles = result
    assert isinstance(tools, list)
    assert isinstance(flex_bubbles, list)
    assert len(flex_bubbles) == 0


def test_format_response_tool_populates_flex_bubbles():
    from spend_tracking.lambdas.services.agent import build_tools

    tools, flex_bubbles = build_tools("postgresql://fake")
    # Find the format_response tool
    fmt_tool = None
    for t in tools:
        if hasattr(t, "name") and t.name == "format_response":
            fmt_tool = t
            break
    assert fmt_tool is not None

    # Call it
    result = fmt_tool.func(
        title="Test Title",
        sections=[
            {
                "type": "key_value",
                "items": [{"label": "Total", "value": "NT$100"}],
            }
        ],
    )

    assert "Test Title" in result
    assert len(flex_bubbles) == 1
    assert flex_bubbles[0]["type"] == "bubble"
    assert flex_bubbles[0]["header"]["contents"][0]["text"] == "Test Title"


def test_execute_sends_flex_and_text_when_format_response_used():
    from spend_tracking.lambdas.services.process_line_message import (
        ProcessLineMessage,
    )

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = _make_user_message()
    mock_repo.load_history.return_value = []

    mock_final_message = MagicMock()
    mock_final_message.content = [MagicMock(type="text", text="Summary text")]
    mock_final_message.model = "claude-opus-4-6"
    mock_final_message.stop_reason = "end_turn"
    mock_final_message.usage = MagicMock(input_tokens=100, output_tokens=50)

    mock_runner = MagicMock()
    mock_runner.__iter__ = MagicMock(return_value=iter([mock_final_message]))

    mock_client = MagicMock()
    mock_client.beta.messages.tool_runner.return_value = mock_runner

    mock_push = MagicMock()

    # Pre-populate flex_bubbles to simulate format_response calls
    fake_bubble = {"type": "bubble", "header": {"contents": [{"text": "Test"}]}}

    service = ProcessLineMessage(
        client=mock_client,
        model="claude-opus-4-6",
        chat_message_repository=mock_repo,
        line_push_sender=mock_push,
        db_connection_string="postgresql://fake",
    )

    # Monkey-patch build_tools to return pre-populated flex_bubbles
    import spend_tracking.lambdas.services.process_line_message as plm

    original_build_tools = plm.build_tools
    plm.build_tools = lambda conn: (  # type: ignore[assignment]
        original_build_tools(conn)[0],
        [fake_bubble],
    )
    try:
        service.execute(chat_message_id=42)
    finally:
        plm.build_tools = original_build_tools

    mock_push.send_messages.assert_called_once()
    messages = mock_push.send_messages.call_args[0][1]
    assert len(messages) == 2
    assert messages[0]["type"] == "flex"
    assert messages[1]["type"] == "text"
    assert messages[1]["text"] == "Summary text"

    # DB still saves text content
    saved = mock_repo.save.call_args[0][0]
    assert saved.content == "Summary text"


def test_execute_sends_text_only_when_no_flex():
    """When agent doesn't use format_response, falls back to text-only."""
    from spend_tracking.lambdas.services.process_line_message import (
        ProcessLineMessage,
    )

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = _make_user_message()
    mock_repo.load_history.return_value = []

    mock_final_message = MagicMock()
    mock_final_message.content = [MagicMock(type="text", text="Simple reply")]
    mock_final_message.model = "claude-opus-4-6"
    mock_final_message.stop_reason = "end_turn"
    mock_final_message.usage = MagicMock(input_tokens=100, output_tokens=50)

    mock_runner = MagicMock()
    mock_runner.__iter__ = MagicMock(return_value=iter([mock_final_message]))

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

    # Should use send_messages with text only
    mock_push.send_messages.assert_called_once()
    messages = mock_push.send_messages.call_args[0][1]
    assert len(messages) == 1
    assert messages[0]["type"] == "text"


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
