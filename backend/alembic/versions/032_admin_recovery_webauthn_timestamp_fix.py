"""admin_recovery_webauthn_timestamp_fix

Revision ID: 032_admin_recovery_webauthn_timestamp_fix
Revises: 031_r2_posts_moderation_timezone_stabilization
Create Date: 2026-04-15 14:30:00.000000
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "032_admin_recovery_webauthn_timestamp_fix"
down_revision: Union[str, None] = "031_r2_posts_moderation_timezone_stabilization"
branch_labels = None
depends_on = None


def _alter_timestamp_column(column_name: str, *, nullable: bool, timezone_aware: bool) -> None:
    bind = op.get_bind()
    kwargs = {
        "existing_type": sa.DateTime(timezone=not timezone_aware),
        "type_": sa.DateTime(timezone=timezone_aware),
        "existing_nullable": nullable,
    }
    if bind.dialect.name == "postgresql":
        kwargs["postgresql_using"] = f"{column_name} AT TIME ZONE 'UTC'"
    op.alter_column("webauthn_credentials", column_name, **kwargs)


def upgrade() -> None:
    _alter_timestamp_column("created_at", nullable=False, timezone_aware=True)
    _alter_timestamp_column("last_used_at", nullable=True, timezone_aware=True)


def downgrade() -> None:
    _alter_timestamp_column("last_used_at", nullable=True, timezone_aware=False)
    _alter_timestamp_column("created_at", nullable=False, timezone_aware=False)
