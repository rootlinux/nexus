"""add code_hash to invite_codes

Revision ID: 036_invite_code_hash
Revises: 035_add_follows_index_for_discover
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "036_invite_code_hash"
down_revision = "035_add_follows_index_for_discover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invite_codes", sa.Column("code_hash", sa.String(64), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(text("SELECT id, code FROM invite_codes WHERE code IS NOT NULL")).fetchall()
    if rows:
        import hashlib
        updates = [{"h": hashlib.sha256(row.code.encode()).hexdigest(), "i": row.id} for row in rows]
        conn.execute(
            text("UPDATE invite_codes SET code_hash = :h WHERE id = :i"),
            updates,
        )

    op.create_index("ix_invite_codes_code_hash", "invite_codes", ["code_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_invite_codes_code_hash", table_name="invite_codes")
    op.drop_column("invite_codes", "code_hash")
