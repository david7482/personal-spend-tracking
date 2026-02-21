"""add transactions

Revision ID: 002
Revises: 001
Create Date: 2026-02-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, Sequence[str], None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE transactions (
            id              BIGSERIAL PRIMARY KEY,
            source_type     TEXT NOT NULL,
            source_id       BIGINT,
            bank            TEXT NOT NULL,
            transaction_at  TIMESTAMPTZ NOT NULL,
            region          TEXT,
            amount          NUMERIC(12,2) NOT NULL,
            currency        TEXT NOT NULL DEFAULT 'TWD',
            merchant        TEXT,
            category        TEXT,
            notes           TEXT,
            raw_data        JSONB,
            created_at      TIMESTAMPTZ DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transactions")
