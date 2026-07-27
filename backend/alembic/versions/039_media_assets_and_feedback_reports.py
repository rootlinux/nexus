"""Add media_assets, feedback_reports, and user_media_quota tables

Revision ID: 039_media_assets_and_feedback_reports
Revises: 038_admin_audit_service_context
Create Date: 2026-07-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "039_media_assets_and_feedback_reports"
down_revision: Union[str, None] = "038_admin_audit_service_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


media_asset_type_enum = sa.Enum(
    "avatar", "cover", "post_image", "feedback_attachment", name="mediaassettype"
)
media_asset_status_enum = sa.Enum(
    "pending", "attached", "deletion_pending", name="mediaassetstatus"
)


def upgrade() -> None:
    # All three tables are brand-new — no backfill needed. Pre-existing files in
    # backend/uploads/ and backend/feedback_private_uploads/ are explicitly out of
    # scope for this round; user_media_quota rows are created lazily on first
    # upload per user, not backfilled from historical usage.
    op.create_table(
        "feedback_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "submitter_user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feedback_reports_submitter_user_id", "feedback_reports", ["submitter_user_id"])
    op.create_index("ix_feedback_reports_created_at", "feedback_reports", ["created_at"])

    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("media_type", media_asset_type_enum, nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False, unique=True),
        sa.Column("storage_provider", sa.String(32), nullable=False, server_default="local"),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", media_asset_status_enum, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attached_to_type", sa.String(32), nullable=True),
        sa.Column("attached_to_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_media_assets_owner_user_id", "media_assets", ["owner_user_id"])
    op.create_index("ix_media_assets_storage_key", "media_assets", ["storage_key"], unique=True)
    op.create_index("ix_media_assets_media_type", "media_assets", ["media_type"])
    op.create_index("ix_media_assets_status", "media_assets", ["status"])
    op.create_index("ix_media_assets_created_at", "media_assets", ["created_at"])
    op.create_index("ix_media_assets_owner_status", "media_assets", ["owner_user_id", "status"])
    op.create_index("ix_media_assets_status_created_at", "media_assets", ["status", "created_at"])
    op.create_index("ix_media_assets_attached_to", "media_assets", ["attached_to_type", "attached_to_id"])

    op.create_table(
        "user_media_quota",
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_window_started_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_media_quota")

    op.drop_index("ix_media_assets_attached_to", table_name="media_assets")
    op.drop_index("ix_media_assets_status_created_at", table_name="media_assets")
    op.drop_index("ix_media_assets_owner_status", table_name="media_assets")
    op.drop_index("ix_media_assets_created_at", table_name="media_assets")
    op.drop_index("ix_media_assets_status", table_name="media_assets")
    op.drop_index("ix_media_assets_media_type", table_name="media_assets")
    op.drop_index("ix_media_assets_storage_key", table_name="media_assets")
    op.drop_index("ix_media_assets_owner_user_id", table_name="media_assets")
    op.drop_table("media_assets")

    op.drop_index("ix_feedback_reports_created_at", table_name="feedback_reports")
    op.drop_index("ix_feedback_reports_submitter_user_id", table_name="feedback_reports")
    op.drop_table("feedback_reports")

    # Postgres enum types aren't auto-dropped by DROP TABLE.
    media_asset_status_enum.drop(op.get_bind(), checkfirst=True)
    media_asset_type_enum.drop(op.get_bind(), checkfirst=True)
