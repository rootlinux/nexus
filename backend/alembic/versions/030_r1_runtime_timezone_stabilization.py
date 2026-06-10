"""r1_runtime_timezone_stabilization

Revision ID: 030_r1_runtime_timezone_stabilization
Revises: 029_auth_token_timestamps_timezone_fix
Create Date: 2026-04-14 16:30:00.000000
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "030_r1_runtime_timezone_stabilization"
down_revision: Union[str, None] = "029_auth_token_timestamps_timezone_fix"
branch_labels = None
depends_on = None


def _alter_timestamp_column(table_name: str, column_name: str, *, nullable: bool, timezone_aware: bool) -> None:
    bind = op.get_bind()
    kwargs = {
        "existing_type": sa.DateTime(timezone=not timezone_aware),
        "type_": sa.DateTime(timezone=timezone_aware),
        "existing_nullable": nullable,
    }
    if bind.dialect.name == "postgresql":
        kwargs["postgresql_using"] = f"{column_name} AT TIME ZONE 'UTC'"
    op.alter_column(table_name, column_name, **kwargs)


def upgrade() -> None:
    _alter_timestamp_column("invite_codes", "expires_at", nullable=True, timezone_aware=True)
    _alter_timestamp_column("invite_codes", "used_at", nullable=True, timezone_aware=True)
    _alter_timestamp_column("invite_usages", "used_at", nullable=False, timezone_aware=True)

    _alter_timestamp_column("email_verification_tokens", "expires_at", nullable=False, timezone_aware=True)
    _alter_timestamp_column("email_verification_tokens", "created_at", nullable=False, timezone_aware=True)
    _alter_timestamp_column("email_verification_tokens", "used_at", nullable=True, timezone_aware=True)
    _alter_timestamp_column("email_verification_tokens", "revoked_at", nullable=True, timezone_aware=True)

    _alter_timestamp_column("email_change_tokens", "expires_at", nullable=False, timezone_aware=True)
    _alter_timestamp_column("email_change_tokens", "created_at", nullable=False, timezone_aware=True)
    _alter_timestamp_column("email_change_tokens", "used_at", nullable=True, timezone_aware=True)
    _alter_timestamp_column("email_change_tokens", "revoked_at", nullable=True, timezone_aware=True)


def downgrade() -> None:
    _alter_timestamp_column("email_change_tokens", "revoked_at", nullable=True, timezone_aware=False)
    _alter_timestamp_column("email_change_tokens", "used_at", nullable=True, timezone_aware=False)
    _alter_timestamp_column("email_change_tokens", "created_at", nullable=False, timezone_aware=False)
    _alter_timestamp_column("email_change_tokens", "expires_at", nullable=False, timezone_aware=False)

    _alter_timestamp_column("email_verification_tokens", "revoked_at", nullable=True, timezone_aware=False)
    _alter_timestamp_column("email_verification_tokens", "used_at", nullable=True, timezone_aware=False)
    _alter_timestamp_column("email_verification_tokens", "created_at", nullable=False, timezone_aware=False)
    _alter_timestamp_column("email_verification_tokens", "expires_at", nullable=False, timezone_aware=False)

    _alter_timestamp_column("invite_usages", "used_at", nullable=False, timezone_aware=False)
    _alter_timestamp_column("invite_codes", "used_at", nullable=True, timezone_aware=False)
    _alter_timestamp_column("invite_codes", "expires_at", nullable=True, timezone_aware=False)
