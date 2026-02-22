"""drop body_html from emails

Revision ID: 004
Revises: 003
Create Date: 2026-02-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, Sequence[str], None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE emails DROP COLUMN body_html")


def downgrade() -> None:
    op.execute("ALTER TABLE emails ADD COLUMN body_html TEXT")
