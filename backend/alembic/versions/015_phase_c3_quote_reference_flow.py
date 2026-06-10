"""Phase C.3 quote reference flow

Revision ID: 015_quote_reference_flow
Revises: 014_phase_c2_bookmark_integrity
Create Date: 2026-03-29 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015_quote_reference_flow"
down_revision: Union[str, None] = "014_phase_c2_bookmark_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("quoted_post_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_posts_quoted_post_id_posts",
        "posts",
        "posts",
        ["quoted_post_id"],
        ["id"],
    )
    op.create_index("ix_posts_quoted_post_id", "posts", ["quoted_post_id"], unique=False)

    op.execute(sa.text("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'quote'"))


def downgrade() -> None:
    op.drop_index("ix_posts_quoted_post_id", table_name="posts")
    op.drop_constraint("fk_posts_quoted_post_id_posts", "posts", type_="foreignkey")
    op.drop_column("posts", "quoted_post_id")
