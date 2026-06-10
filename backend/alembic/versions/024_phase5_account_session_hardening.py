"""phase5_account_session_hardening

Revision ID: 024_phase5_account_session_hardening
Revises: 023_email_canonicalization
Create Date: 2026-04-08 22:00:00.000000
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "024_phase5_account_session_hardening"
down_revision: Union[str, None] = "023_email_canonicalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("last_used_at", sa.DateTime(), nullable=True))
    op.add_column("refresh_tokens", sa.Column("device_label", sa.String(length=255), nullable=True))
    op.create_index("ix_refresh_tokens_last_used_at", "refresh_tokens", ["last_used_at"], unique=False)
    op.execute(sa.text("UPDATE refresh_tokens SET last_used_at = created_at WHERE last_used_at IS NULL"))

    op.create_table(
        "email_change_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("pending_email", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("requested_by_ip", sa.String(length=64), nullable=True),
        sa.Column("requested_user_agent", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_email_change_tokens_token_hash"),
    )
    op.create_index("ix_email_change_tokens_user_id", "email_change_tokens", ["user_id"], unique=False)
    op.create_index("ix_email_change_tokens_pending_email", "email_change_tokens", ["pending_email"], unique=False)
    op.create_index("ix_email_change_tokens_token_hash", "email_change_tokens", ["token_hash"], unique=True)
    op.create_index("ix_email_change_tokens_expires_at", "email_change_tokens", ["expires_at"], unique=False)
    op.create_index("ix_email_change_tokens_used_at", "email_change_tokens", ["used_at"], unique=False)
    op.create_index("ix_email_change_tokens_revoked_at", "email_change_tokens", ["revoked_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_email_change_tokens_revoked_at", table_name="email_change_tokens")
    op.drop_index("ix_email_change_tokens_used_at", table_name="email_change_tokens")
    op.drop_index("ix_email_change_tokens_expires_at", table_name="email_change_tokens")
    op.drop_index("ix_email_change_tokens_token_hash", table_name="email_change_tokens")
    op.drop_index("ix_email_change_tokens_pending_email", table_name="email_change_tokens")
    op.drop_index("ix_email_change_tokens_user_id", table_name="email_change_tokens")
    op.drop_table("email_change_tokens")

    op.drop_index("ix_refresh_tokens_last_used_at", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "device_label")
    op.drop_column("refresh_tokens", "last_used_at")
