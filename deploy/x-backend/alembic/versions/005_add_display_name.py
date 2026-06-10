"""Add display_name to users table

Revision ID: 005_add_display_name
Revises: 1daa72d4a88f
Create Date: 2026-03-24 11:52:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_add_display_name'
down_revision = '1daa72d4a88f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('display_name', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'display_name')
