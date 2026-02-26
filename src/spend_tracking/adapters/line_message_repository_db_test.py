from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from spend_tracking.domains.models import LineMessage


def _make_line_message() -> LineMessage:
    return LineMessage(
        id=None,
        line_user_id="U1234567890abcdef",
        message_type="text",
        message="Hello",
        reply_token="reply-token-abc",
        raw_event={"type": "message", "message": {"type": "text", "text": "Hello"}},
        timestamp=datetime(2026, 2, 27, 10, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 2, 27, 10, 0, 1, tzinfo=UTC),
    )


@patch("spend_tracking.adapters.line_message_repository_db.boto3")
@patch("spend_tracking.adapters.line_message_repository_db.psycopg2")
def test_save_line_message_inserts_and_sets_id(mock_psycopg2, mock_boto3):
    from spend_tracking.adapters.line_message_repository_db import (
        DbLineMessageRepository,
    )

    mock_boto3.client.return_value.get_parameter.return_value = {
        "Parameter": {"Value": "postgresql://fake"}
    }
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (42,)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_psycopg2.connect.return_value = mock_conn

    repo = DbLineMessageRepository("ssm-param-name")
    msg = _make_line_message()
    repo.save_line_message(msg)

    mock_cur.execute.assert_called_once()
    sql = mock_cur.execute.call_args[0][0]
    assert "INSERT INTO line_messages" in sql
    assert "RETURNING id" in sql
    assert msg.id == 42
    mock_conn.commit.assert_called_once()
