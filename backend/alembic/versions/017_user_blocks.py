"""add user block relationships

Revision ID: 017_user_blocks
Revises: 016_phase_a9_invite_code_length
Create Date: 2026-03-31 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "017_user_blocks"
down_revision = "016_phase_a9_invite_code_length"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("blocker_id", sa.Integer(), nullable=False),
        sa.Column("blocked_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["blocked_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["blocker_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_blocks_blocker_blocked"),
    )
    op.create_index(op.f("ix_blocks_id"), "blocks", ["id"], unique=False)
    op.create_index(op.f("ix_blocks_blocker_id"), "blocks", ["blocker_id"], unique=False)
    op.create_index(op.f("ix_blocks_blocked_id"), "blocks", ["blocked_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_blocks_blocked_id"), table_name="blocks")
    op.drop_index(op.f("ix_blocks_blocker_id"), table_name="blocks")
    op.drop_index(op.f("ix_blocks_id"), table_name="blocks")
    op.drop_table("blocks")
