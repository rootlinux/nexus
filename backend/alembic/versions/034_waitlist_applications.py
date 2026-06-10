"""waitlist_applications

Revision ID: 034_waitlist_applications
Revises: 033_push_subscriptions_web_push
Create Date: 2026-04-19 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "034_waitlist_applications"
down_revision: Union[str, None] = "033_push_subscriptions_web_push"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    waitlist_status_enum = postgresql.ENUM(
        "new", "reviewed", "approved", "rejected",
        name="waitlistapplicationstatus",
        create_type=False
    )
    waitlist_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "waitlist_applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("contact", sa.String(length=255), nullable=False),
        sa.Column("preferred_username", sa.String(length=50), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("referral_source", sa.String(length=255), nullable=True),
        sa.Column("social_url", sa.String(length=500), nullable=True),
        sa.Column(
            "status",
            waitlist_status_enum,
            nullable=False,
            server_default="new"
        ),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("invite_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["invite_id"], ["invite_codes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_waitlist_applications_id", "waitlist_applications", ["id"], unique=False)
    op.create_index("ix_waitlist_applications_contact", "waitlist_applications", ["contact"], unique=False)
    op.create_index("ix_waitlist_applications_preferred_username", "waitlist_applications", ["preferred_username"], unique=False)
    op.create_index("ix_waitlist_applications_status", "waitlist_applications", ["status"], unique=False)
    op.create_index("ix_waitlist_applications_invite_id", "waitlist_applications", ["invite_id"], unique=False)
    op.create_index("ix_waitlist_applications_created_at", "waitlist_applications", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_waitlist_applications_created_at", table_name="waitlist_applications")
    op.drop_index("ix_waitlist_applications_invite_id", table_name="waitlist_applications")
    op.drop_index("ix_waitlist_applications_status", table_name="waitlist_applications")
    op.drop_index("ix_waitlist_applications_preferred_username", table_name="waitlist_applications")
    op.drop_index("ix_waitlist_applications_contact", table_name="waitlist_applications")
    op.drop_index("ix_waitlist_applications_id", table_name="waitlist_applications")
    op.drop_table("waitlist_applications")

    waitlist_status_enum = postgresql.ENUM(
        "new", "reviewed", "approved", "rejected",
        name="waitlistapplicationstatus",
        create_type=False
    )
    waitlist_status_enum.drop(bind, checkfirst=True)
