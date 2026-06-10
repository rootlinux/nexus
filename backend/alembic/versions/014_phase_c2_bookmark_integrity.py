"""Phase C.2 bookmark integrity hardening

Revision ID: 014_phase_c2_bookmark_integrity
Revises: 013_phase_a5_queue
Create Date: 2026-03-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "014_phase_c2_bookmark_integrity"
down_revision: Union[str, None] = "013_phase_a5_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bookmarks_v2",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "post_id", name="uq_bookmarks_v2_user_post"),
    )
    op.create_index(op.f("ix_bookmarks_v2_id"), "bookmarks_v2", ["id"], unique=False)
    op.create_index(op.f("ix_bookmarks_v2_user_id"), "bookmarks_v2", ["user_id"], unique=False)
    op.create_index(op.f("ix_bookmarks_v2_post_id"), "bookmarks_v2", ["post_id"], unique=False)
    op.create_index("ix_bookmarks_v2_created_at", "bookmarks_v2", ["created_at"], unique=False)

    op.execute(
        """
        INSERT INTO bookmarks_v2 (id, user_id, post_id, created_at)
        SELECT id, user_id, post_id, created_at
        FROM bookmarks
        """
    )

    op.drop_index(op.f("ix_bookmarks_post_id"), table_name="bookmarks")
    op.drop_index(op.f("ix_bookmarks_user_id"), table_name="bookmarks")
    op.drop_index(op.f("ix_bookmarks_id"), table_name="bookmarks")
    op.drop_table("bookmarks")

    op.rename_table("bookmarks_v2", "bookmarks")
    op.drop_index(op.f("ix_bookmarks_v2_id"), table_name="bookmarks")
    op.drop_index(op.f("ix_bookmarks_v2_user_id"), table_name="bookmarks")
    op.drop_index(op.f("ix_bookmarks_v2_post_id"), table_name="bookmarks")
    op.drop_index("ix_bookmarks_v2_created_at", table_name="bookmarks")
    op.create_index(op.f("ix_bookmarks_id"), "bookmarks", ["id"], unique=False)
    op.create_index(op.f("ix_bookmarks_user_id"), "bookmarks", ["user_id"], unique=False)
    op.create_index(op.f("ix_bookmarks_post_id"), "bookmarks", ["post_id"], unique=False)
    op.create_index("ix_bookmarks_created_at", "bookmarks", ["created_at"], unique=False)
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('bookmarks', 'id'),
            COALESCE((SELECT MAX(id) FROM bookmarks), 1),
            (SELECT COUNT(*) > 0 FROM bookmarks)
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_bookmarks_created_at", table_name="bookmarks")

    op.create_table(
        "bookmarks_legacy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "post_id", name="uq_bookmarks_legacy_user_post"),
    )
    op.create_index(op.f("ix_bookmarks_legacy_id"), "bookmarks_legacy", ["id"], unique=False)
    op.create_index(op.f("ix_bookmarks_legacy_user_id"), "bookmarks_legacy", ["user_id"], unique=False)
    op.create_index(op.f("ix_bookmarks_legacy_post_id"), "bookmarks_legacy", ["post_id"], unique=False)

    op.execute(
        """
        INSERT INTO bookmarks_legacy (id, user_id, post_id, created_at)
        SELECT id, user_id, post_id, created_at
        FROM bookmarks
        """
    )

    op.drop_index(op.f("ix_bookmarks_post_id"), table_name="bookmarks")
    op.drop_index(op.f("ix_bookmarks_user_id"), table_name="bookmarks")
    op.drop_index(op.f("ix_bookmarks_id"), table_name="bookmarks")
    op.drop_table("bookmarks")

    op.rename_table("bookmarks_legacy", "bookmarks")
    op.drop_index(op.f("ix_bookmarks_legacy_id"), table_name="bookmarks")
    op.drop_index(op.f("ix_bookmarks_legacy_user_id"), table_name="bookmarks")
    op.drop_index(op.f("ix_bookmarks_legacy_post_id"), table_name="bookmarks")
    op.create_index(op.f("ix_bookmarks_id"), "bookmarks", ["id"], unique=False)
    op.create_index(op.f("ix_bookmarks_user_id"), "bookmarks", ["user_id"], unique=False)
    op.create_index(op.f("ix_bookmarks_post_id"), "bookmarks", ["post_id"], unique=False)
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('bookmarks', 'id'),
            COALESCE((SELECT MAX(id) FROM bookmarks), 1),
            (SELECT COUNT(*) > 0 FROM bookmarks)
        )
        """
    )
