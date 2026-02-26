"""add line_messages table

Revision ID: 005
Revises: 004
Create Date: 2026-02-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, Sequence[str], None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE line_messages (
            id            BIGSERIAL PRIMARY KEY,
            line_user_id  TEXT NOT NULL,
            message_type  TEXT NOT NULL,
            message       TEXT,
            reply_token   TEXT,
            raw_event     JSONB NOT NULL,
            timestamp     TIMESTAMPTZ NOT NULL,
            created_at    TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_line_messages_user_id ON line_messages(line_user_id)")
    op.execute("CREATE INDEX idx_line_messages_timestamp ON line_messages(timestamp DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS line_messages")
