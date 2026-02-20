"""initial schema

Revision ID: 001
Revises: 
Create Date: 2026-02-21 05:27:21.620112

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE registered_addresses (
            id          BIGSERIAL PRIMARY KEY,
            address     TEXT UNIQUE NOT NULL,
            prefix      TEXT NOT NULL,
            label       TEXT,
            is_active   BOOLEAN DEFAULT true,
            created_at  TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE emails (
            id          BIGSERIAL PRIMARY KEY,
            address     TEXT NOT NULL REFERENCES registered_addresses(address),
            sender      TEXT NOT NULL,
            subject     TEXT,
            body_html   TEXT,
            body_text   TEXT,
            raw_s3_key  TEXT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            parsed_data JSONB,
            created_at  TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_emails_address ON emails(address)")
    op.execute("CREATE INDEX idx_emails_received_at ON emails(received_at DESC)")
    op.execute("CREATE INDEX idx_emails_parsed_data ON emails USING GIN(parsed_data)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS emails")
    op.execute("DROP TABLE IF EXISTS registered_addresses")
