"""Allow invite_codes.created_by_id to be nulled out when the creator is deleted

Revision ID: 037_invite_created_by_nullable
Revises: 036_invite_code_hash
Create Date: 2026-07-24 22:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "037_invite_created_by_nullable"
down_revision: Union[str, None] = "036_invite_code_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("invite_codes_created_by_id_fkey", "invite_codes", type_="foreignkey")
    op.alter_column("invite_codes", "created_by_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key(
        "invite_codes_created_by_id_fkey",
        "invite_codes",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("invite_codes_created_by_id_fkey", "invite_codes", type_="foreignkey")
    op.execute(sa.text("DELETE FROM invite_codes WHERE created_by_id IS NULL"))
    op.alter_column("invite_codes", "created_by_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        "invite_codes_created_by_id_fkey",
        "invite_codes",
        "users",
        ["created_by_id"],
        ["id"],
    )
