"""Add refresh_token_families table and replay-detection lineage columns

Revision ID: 040_refresh_token_families
Revises: 039_media_assets_and_feedback_reports
Create Date: 2026-07-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "040_refresh_token_families"
down_revision: Union[str, None] = "039_media_assets_and_feedback_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "refresh_token_families",
        sa.Column("token_family_id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column("refresh_tokens", sa.Column("token_family_id", sa.String(36), nullable=True))
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "parent_token_id", sa.Integer(),
            sa.ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True,
        ),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "replaced_by_token_id", sa.Integer(),
            sa.ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True,
        ),
    )
    op.add_column("refresh_tokens", sa.Column("reuse_detected_at", sa.DateTime(timezone=True), nullable=True))

    # Each pre-migration token becomes its own single-token family,
    # deterministic from its own PK — no extension required.
    op.execute("UPDATE refresh_tokens SET token_family_id = 'legacy-' || id::text WHERE token_family_id IS NULL")

    # Backfill the anchor rows those synthesized families need to be lockable
    # at all — without this, lock_token_family would have no row to lock for
    # any pre-migration token's family, and the very first post-migration
    # refresh for such a token would find nothing to serialize against.
    op.execute(
        "INSERT INTO refresh_token_families (token_family_id, created_at) "
        "SELECT DISTINCT token_family_id, now() FROM refresh_tokens "
        "WHERE token_family_id LIKE 'legacy-%' ON CONFLICT DO NOTHING"
    )

    op.alter_column("refresh_tokens", "token_family_id", nullable=False)

    op.create_index("ix_refresh_tokens_token_family_id", "refresh_tokens", ["token_family_id"])
    op.create_index("ix_refresh_tokens_parent_token_id", "refresh_tokens", ["parent_token_id"])
    op.create_index("ix_refresh_tokens_replaced_by_token_id", "refresh_tokens", ["replaced_by_token_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_replaced_by_token_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_parent_token_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_token_family_id", table_name="refresh_tokens")

    op.drop_column("refresh_tokens", "reuse_detected_at")
    op.drop_column("refresh_tokens", "replaced_by_token_id")
    op.drop_column("refresh_tokens", "parent_token_id")
    op.drop_column("refresh_tokens", "token_family_id")

    op.drop_table("refresh_token_families")
