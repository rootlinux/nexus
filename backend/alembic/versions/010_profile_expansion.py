"""profile_expansion

Revision ID: 010_profile_expansion
Revises: 009_phase1_control_plane
Create Date: 2026-03-26 13:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010_profile_expansion"
down_revision: Union[str, None] = "009_phase1_control_plane"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("cover_url", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("location", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("website", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "website")
    op.drop_column("users", "location")
    op.drop_column("users", "cover_url")
