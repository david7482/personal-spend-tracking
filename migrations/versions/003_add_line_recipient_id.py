"""add line_recipient_id to registered_addresses

Revision ID: 003
Revises: 002
Create Date: 2026-02-22

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, Sequence[str], None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE registered_addresses ADD COLUMN line_recipient_id TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE registered_addresses DROP COLUMN line_recipient_id"
    )
