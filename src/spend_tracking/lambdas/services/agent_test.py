from unittest.mock import MagicMock

from spend_tracking.lambdas.services.agent import (
    FALLBACK_MESSAGE,
    SYSTEM_PROMPT,
    build_tools,
    extract_text,
    run_agent,
    validate_sql,
)


def test_system_prompt_is_nonempty_string():
    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 0


def test_validate_sql_allows_select():
    assert validate_sql("SELECT * FROM transactions") is True
    assert validate_sql("select count(*) from transactions") is True
    assert validate_sql("WITH cte AS (SELECT 1) SELECT * FROM cte") is True


def test_validate_sql_rejects_mutations():
    assert validate_sql("DROP TABLE transactions") is False
    assert validate_sql("DELETE FROM transactions") is False
    assert validate_sql("INSERT INTO transactions VALUES (1)") is False
    assert validate_sql("UPDATE transactions SET amount = 0") is False


def test_build_tools_returns_two_tools():
    tools = build_tools("postgresql://fake")
    assert len(tools) == 2


def test_extract_text_returns_text_from_message():
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(type="text", text="Hello world")]
    assert extract_text(mock_msg) == "Hello world"


def test_extract_text_joins_multiple_text_blocks():
    block1 = MagicMock(type="text", text="Hello")
    block2 = MagicMock(type="tool_use")
    block2.type = "tool_use"
    block3 = MagicMock(type="text", text="world")
    mock_msg = MagicMock()
    mock_msg.content = [block1, block2, block3]
    assert extract_text(mock_msg) == "Hello\nworld"


def test_extract_text_returns_fallback_when_no_text():
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(type="tool_use")]
    mock_msg.content[0].type = "tool_use"
    assert extract_text(mock_msg) == FALLBACK_MESSAGE


def test_run_agent_yields_messages_from_tool_runner():
    mock_msg1 = MagicMock()
    mock_msg2 = MagicMock()
    mock_runner = MagicMock()
    mock_runner.__iter__ = MagicMock(return_value=iter([mock_msg1, mock_msg2]))

    mock_client = MagicMock()
    mock_client.beta.messages.tool_runner.return_value = mock_runner

    tools = [MagicMock(), MagicMock()]
    messages = [{"role": "user", "content": "Hi"}]

    yielded = list(run_agent(mock_client, "claude-opus-4-6", tools, messages))

    assert yielded == [mock_msg1, mock_msg2]
    mock_client.beta.messages.tool_runner.assert_called_once()
