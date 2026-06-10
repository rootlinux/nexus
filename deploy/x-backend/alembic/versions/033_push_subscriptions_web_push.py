"""push_subscriptions_web_push

Revision ID: 033_push_subscriptions_web_push
Revises: 032_admin_recovery_webauthn_timestamp_fix
Create Date: 2026-04-18 11:30:00.000000
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "033_push_subscriptions_web_push"
down_revision: Union[str, None] = "032_admin_recovery_webauthn_timestamp_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(length=2000), nullable=False),
        sa.Column("p256dh", sa.String(length=512), nullable=False),
        sa.Column("auth", sa.String(length=512), nullable=False),
        sa.Column("user_agent", sa.String(length=1000), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
    )
    op.create_index("ix_push_subscriptions_id", "push_subscriptions", ["id"], unique=False)
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"], unique=False)
    op.create_index("ix_push_subscriptions_endpoint", "push_subscriptions", ["endpoint"], unique=True)
    op.create_index("ix_push_subscriptions_is_active", "push_subscriptions", ["is_active"], unique=False)
    op.create_index("ix_push_subscriptions_last_seen_at", "push_subscriptions", ["last_seen_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_last_seen_at", table_name="push_subscriptions")
    op.drop_index("ix_push_subscriptions_is_active", table_name="push_subscriptions")
    op.drop_index("ix_push_subscriptions_endpoint", table_name="push_subscriptions")
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_index("ix_push_subscriptions_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
