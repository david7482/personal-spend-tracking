from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from spend_tracking.domains.models import ChatMessage


def _make_chat_message(role: str = "user") -> ChatMessage:
    return ChatMessage(
        id=None,
        line_user_id="U1234567890abcdef",
        role=role,
        content="Hello",
        message_type="text",
        raw_event={"type": "message"},
        timestamp=datetime(2026, 2, 27, 10, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 2, 27, 10, 0, 1, tzinfo=UTC),
    )


def _mock_db():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cur


@patch("spend_tracking.adapters.chat_message_repository_db.boto3")
@patch("spend_tracking.adapters.chat_message_repository_db.psycopg2")
def test_save_inserts_and_sets_id(mock_psycopg2, mock_boto3):
    from spend_tracking.adapters.chat_message_repository_db import (
        DbChatMessageRepository,
    )

    mock_boto3.client.return_value.get_parameter.return_value = {
        "Parameter": {"Value": "postgresql://fake"}
    }
    mock_conn, mock_cur = _mock_db()
    mock_cur.fetchone.return_value = (42,)
    mock_psycopg2.connect.return_value = mock_conn

    repo = DbChatMessageRepository("ssm-param-name")
    msg = _make_chat_message()
    repo.save(msg)

    mock_cur.execute.assert_called_once()
    sql = mock_cur.execute.call_args[0][0]
    assert "INSERT INTO chat_messages" in sql
    assert "RETURNING id" in sql
    assert msg.id == 42
    mock_conn.commit.assert_called_once()


@patch("spend_tracking.adapters.chat_message_repository_db.boto3")
@patch("spend_tracking.adapters.chat_message_repository_db.psycopg2")
def test_load_history_returns_ordered_messages(mock_psycopg2, mock_boto3):
    from spend_tracking.adapters.chat_message_repository_db import (
        DbChatMessageRepository,
    )

    mock_boto3.client.return_value.get_parameter.return_value = {
        "Parameter": {"Value": "postgresql://fake"}
    }
    mock_conn, mock_cur = _mock_db()
    # DB returns DESC order (newest first), reversed() makes it chronological
    mock_cur.fetchall.return_value = [
        (2, "U123", "assistant", "Hello!", "text", None,
         datetime(2026, 2, 27, 9, 0, 1, tzinfo=UTC),
         datetime(2026, 2, 27, 9, 0, 1, tzinfo=UTC)),
        (1, "U123", "user", "Hi", "text", None,
         datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC),
         datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC)),
    ]
    mock_psycopg2.connect.return_value = mock_conn

    repo = DbChatMessageRepository("ssm-param-name")
    messages = repo.load_history("U123", limit=20)

    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    sql = mock_cur.execute.call_args[0][0]
    assert "ORDER BY created_at DESC" in sql
    assert "LIMIT" in sql


@patch("spend_tracking.adapters.chat_message_repository_db.boto3")
@patch("spend_tracking.adapters.chat_message_repository_db.psycopg2")
def test_get_by_id_returns_message(mock_psycopg2, mock_boto3):
    from spend_tracking.adapters.chat_message_repository_db import (
        DbChatMessageRepository,
    )

    mock_boto3.client.return_value.get_parameter.return_value = {
        "Parameter": {"Value": "postgresql://fake"}
    }
    mock_conn, mock_cur = _mock_db()
    mock_cur.fetchone.return_value = (
        42, "U123", "user", "Hi", "text", None,
        datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC),
        datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC),
    )
    mock_psycopg2.connect.return_value = mock_conn

    repo = DbChatMessageRepository("ssm-param-name")
    msg = repo.get_by_id(42)

    assert msg is not None
    assert msg.id == 42
    assert msg.content == "Hi"


@patch("spend_tracking.adapters.chat_message_repository_db.boto3")
@patch("spend_tracking.adapters.chat_message_repository_db.psycopg2")
def test_get_by_id_returns_none_when_not_found(mock_psycopg2, mock_boto3):
    from spend_tracking.adapters.chat_message_repository_db import (
        DbChatMessageRepository,
    )

    mock_boto3.client.return_value.get_parameter.return_value = {
        "Parameter": {"Value": "postgresql://fake"}
    }
    mock_conn, mock_cur = _mock_db()
    mock_cur.fetchone.return_value = None
    mock_psycopg2.connect.return_value = mock_conn

    repo = DbChatMessageRepository("ssm-param-name")
    msg = repo.get_by_id(999)

    assert msg is None
