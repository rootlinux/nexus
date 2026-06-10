"""Phase A.9 invite code length alignment

Revision ID: 016_phase_a9_invite_code_length
Revises: 015_quote_reference_flow
Create Date: 2026-03-30 13:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "016_phase_a9_invite_code_length"
down_revision: Union[str, None] = "015_quote_reference_flow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_code_length(inspector: sa.Inspector) -> int | None:
    for column in inspector.get_columns("invite_codes"):
        if column["name"] == "code":
            column_type = column["type"]
            return getattr(column_type, "length", None)
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    current_length = _get_code_length(inspector)
    if current_length is None or current_length >= 32:
        return

    op.alter_column(
        "invite_codes",
        "code",
        existing_type=sa.String(length=current_length),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    current_length = _get_code_length(inspector)
    if current_length is None or current_length <= 20:
        return

    max_length = bind.execute(sa.text("SELECT COALESCE(MAX(char_length(code)), 0) FROM invite_codes")).scalar_one()
    if max_length > 20:
        return

    op.alter_column(
        "invite_codes",
        "code",
        existing_type=sa.String(length=current_length),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
