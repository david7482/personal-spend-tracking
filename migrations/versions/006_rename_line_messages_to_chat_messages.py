"""rename line_messages to chat_messages

Revision ID: 006
Revises: 005
Create Date: 2026-02-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "006"
down_revision: Union[str, Sequence[str], None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE line_messages RENAME TO chat_messages")
    op.execute("ALTER TABLE chat_messages ADD COLUMN role TEXT")
    op.execute("UPDATE chat_messages SET role = 'user'")
    op.execute("ALTER TABLE chat_messages ALTER COLUMN role SET NOT NULL")
    op.execute("ALTER TABLE chat_messages RENAME COLUMN message TO content")
    op.execute("ALTER TABLE chat_messages DROP COLUMN reply_token")
    op.execute("DROP INDEX IF EXISTS idx_line_messages_user_id")
    op.execute("DROP INDEX IF EXISTS idx_line_messages_timestamp")
    op.execute(
        "CREATE INDEX idx_chat_messages_user_time "
        "ON chat_messages (line_user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_messages_user_time")
    op.execute("ALTER TABLE chat_messages ADD COLUMN reply_token TEXT")
    op.execute("ALTER TABLE chat_messages RENAME COLUMN content TO message")
    op.execute("ALTER TABLE chat_messages DROP COLUMN role")
    op.execute("ALTER TABLE chat_messages RENAME TO line_messages")
    op.execute(
        "CREATE INDEX idx_line_messages_user_id ON line_messages(line_user_id)"
    )
    op.execute(
        "CREATE INDEX idx_line_messages_timestamp ON line_messages(timestamp DESC)"
    )
