"""phase2_secure_admin_actions

Revision ID: 020_phase2_secure_admin_actions
Revises: 019_staff_permissions_phase1
Create Date: 2026-04-08 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "020_phase2_secure_admin_actions"
down_revision: Union[str, None] = "019_staff_permissions_phase1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_users_must_change_password", "users", ["must_change_password"], unique=False)

    op.create_table(
        "admin_password_reset_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_by_user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["issued_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_password_reset_tokens_id", "admin_password_reset_tokens", ["id"], unique=False)
    op.create_index("ix_admin_password_reset_tokens_user_id", "admin_password_reset_tokens", ["user_id"], unique=False)
    op.create_index("ix_admin_password_reset_tokens_token_hash", "admin_password_reset_tokens", ["token_hash"], unique=True)
    op.create_index(
        "ix_admin_password_reset_tokens_issued_by_user_id",
        "admin_password_reset_tokens",
        ["issued_by_user_id"],
        unique=False,
    )
    op.create_index("ix_admin_password_reset_tokens_expires_at", "admin_password_reset_tokens", ["expires_at"], unique=False)
    op.create_index("ix_admin_password_reset_tokens_used_at", "admin_password_reset_tokens", ["used_at"], unique=False)
    op.create_index("ix_admin_password_reset_tokens_revoked_at", "admin_password_reset_tokens", ["revoked_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_admin_password_reset_tokens_revoked_at", table_name="admin_password_reset_tokens")
    op.drop_index("ix_admin_password_reset_tokens_used_at", table_name="admin_password_reset_tokens")
    op.drop_index("ix_admin_password_reset_tokens_expires_at", table_name="admin_password_reset_tokens")
    op.drop_index("ix_admin_password_reset_tokens_issued_by_user_id", table_name="admin_password_reset_tokens")
    op.drop_index("ix_admin_password_reset_tokens_token_hash", table_name="admin_password_reset_tokens")
    op.drop_index("ix_admin_password_reset_tokens_user_id", table_name="admin_password_reset_tokens")
    op.drop_index("ix_admin_password_reset_tokens_id", table_name="admin_password_reset_tokens")
    op.drop_table("admin_password_reset_tokens")

    op.drop_index("ix_users_must_change_password", table_name="users")
    op.drop_column("users", "must_change_password")
