"""refresh_token_device_fingerprint

Revision ID: 018_refresh_token_device_fingerprint
Revises: 017_user_blocks
Create Date: 2026-04-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '018_refresh_token_device_fingerprint'
down_revision: Union[str, None] = '017_user_blocks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic defaults alembic_version.version_num to VARCHAR(32), but this
    # revision id is 36 chars long. Widen before Alembic writes the new head.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.add_column(
        'refresh_tokens',
        sa.Column('device_fingerprint', sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('refresh_tokens', 'device_fingerprint')
