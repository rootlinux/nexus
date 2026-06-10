"""Simplify invites for beta

Revision ID: 008_simplify_invites_for_beta
Revises: 007_inv_usage_audit
Create Date: 2026-03-25 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "008_simplify_invites_for_beta"
down_revision: Union[str, None] = "007_inv_usage_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "invite_codes", "internal_note"):
        op.add_column("invite_codes", sa.Column("internal_note", sa.String(length=255), nullable=True))

    if not _has_column(inspector, "invite_codes", "assigned_to_user_id"):
        op.add_column("invite_codes", sa.Column("assigned_to_user_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_invite_codes_assigned_to_user_id_users",
            "invite_codes",
            "users",
            ["assigned_to_user_id"],
            ["id"],
        )
        op.create_index("ix_invite_codes_assigned_to_user_id", "invite_codes", ["assigned_to_user_id"], unique=False)

    op.execute(sa.text("UPDATE invite_codes SET invite_type = 'generic'"))
    op.execute(sa.text("UPDATE invite_codes SET assigned_to_user_id = inviter_id WHERE assigned_to_user_id IS NULL AND inviter_id IS NOT NULL"))
    op.execute(sa.text("UPDATE invite_codes SET assigned_to_username = NULL"))
    op.execute(sa.text("UPDATE invite_codes SET inviter_id = NULL"))
    op.execute(sa.text("UPDATE invite_codes SET max_uses = 1"))
    op.execute(sa.text("UPDATE invite_codes SET is_active = FALSE WHERE current_uses >= 1"))
    op.execute(sa.text("UPDATE users SET invited_by_user_id = NULL"))


def downgrade() -> None:
    op.drop_column("invite_codes", "internal_note")
