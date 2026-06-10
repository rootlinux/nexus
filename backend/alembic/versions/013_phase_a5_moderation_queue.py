"""phase_a5_moderation_queue

Revision ID: 013_phase_a5_queue
Revises: 012_phase_b3_identity
Create Date: 2026-03-27 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "013_phase_a5_queue"
down_revision: Union[str, None] = "012_phase_b3_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    moderation_surface_enum = postgresql.ENUM(
        "profile_avatar",
        "profile_cover",
        "profile_display_name",
        "profile_bio",
        "post_text",
        "post_media",
        "dm_text",
        "dm_media",
        name="moderationsurface",
    )
    moderation_detection_status_enum = postgresql.ENUM(
        "clean",
        "suspicious",
        "blocked",
        name="moderationdetectionstatus",
    )
    moderation_review_status_enum = postgresql.ENUM(
        "open",
        "resolved",
        "dismissed",
        name="moderationreviewstatus",
    )
    moderation_surface_column_enum = postgresql.ENUM(
        "profile_avatar",
        "profile_cover",
        "profile_display_name",
        "profile_bio",
        "post_text",
        "post_media",
        "dm_text",
        "dm_media",
        name="moderationsurface",
        create_type=False,
    )
    moderation_detection_status_column_enum = postgresql.ENUM(
        "clean",
        "suspicious",
        "blocked",
        name="moderationdetectionstatus",
        create_type=False,
    )
    moderation_review_status_column_enum = postgresql.ENUM(
        "open",
        "resolved",
        "dismissed",
        name="moderationreviewstatus",
        create_type=False,
    )

    bind = op.get_bind()
    moderation_surface_enum.create(bind, checkfirst=True)
    moderation_detection_status_enum.create(bind, checkfirst=True)
    moderation_review_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "moderation_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("dm_message_id", sa.Integer(), nullable=True),
        sa.Column("surface_type", moderation_surface_column_enum, nullable=False),
        sa.Column("detection_status", moderation_detection_status_column_enum, nullable=False),
        sa.Column("review_status", moderation_review_status_column_enum, nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("reason_summary", sa.String(length=500), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_preview", sa.Text(), nullable=True),
        sa.Column("media_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("resolution_action", sa.String(length=100), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["dm_message_id"], ["direct_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_moderation_signals_user_id", "moderation_signals", ["user_id"], unique=False)
    op.create_index("ix_moderation_signals_post_id", "moderation_signals", ["post_id"], unique=False)
    op.create_index("ix_moderation_signals_dm_message_id", "moderation_signals", ["dm_message_id"], unique=False)
    op.create_index("ix_moderation_signals_surface_type", "moderation_signals", ["surface_type"], unique=False)
    op.create_index("ix_moderation_signals_detection_status", "moderation_signals", ["detection_status"], unique=False)
    op.create_index("ix_moderation_signals_review_status", "moderation_signals", ["review_status"], unique=False)
    op.create_index("ix_moderation_signals_risk_score", "moderation_signals", ["risk_score"], unique=False)
    op.create_index("ix_moderation_signals_created_at", "moderation_signals", ["created_at"], unique=False)
    op.create_index("ix_moderation_signals_resolved_by_user_id", "moderation_signals", ["resolved_by_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_moderation_signals_resolved_by_user_id", table_name="moderation_signals")
    op.drop_index("ix_moderation_signals_created_at", table_name="moderation_signals")
    op.drop_index("ix_moderation_signals_risk_score", table_name="moderation_signals")
    op.drop_index("ix_moderation_signals_review_status", table_name="moderation_signals")
    op.drop_index("ix_moderation_signals_detection_status", table_name="moderation_signals")
    op.drop_index("ix_moderation_signals_surface_type", table_name="moderation_signals")
    op.drop_index("ix_moderation_signals_dm_message_id", table_name="moderation_signals")
    op.drop_index("ix_moderation_signals_post_id", table_name="moderation_signals")
    op.drop_index("ix_moderation_signals_user_id", table_name="moderation_signals")
    op.drop_table("moderation_signals")

    bind = op.get_bind()
    postgresql.ENUM(name="moderationreviewstatus").drop(bind, checkfirst=True)
    postgresql.ENUM(name="moderationdetectionstatus").drop(bind, checkfirst=True)
    postgresql.ENUM(name="moderationsurface").drop(bind, checkfirst=True)
