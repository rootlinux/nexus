"""add_mfa_satisfied_to_refresh_tokens

Revision ID: 027_add_mfa_satisfied_to_refresh_tokens
Revises: 026_remove_legacy_admin_mirror
Create Date: 2026-04-09 13:30:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "027_add_mfa_satisfied_to_refresh_tokens"
down_revision: Union[str, None] = "026_remove_legacy_admin_mirror"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "mfa_satisfied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("refresh_tokens", "mfa_satisfied")
