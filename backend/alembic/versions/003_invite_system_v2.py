"""invite_system_v2

Revision ID: 003_invite_system_v2
Revises: 002_posts_likes_follows
Create Date: 2026-03-23 08:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_invite_system_v2'
down_revision: Union[str, None] = '002_posts_likes_follows'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add assigned_to_username column to invite_codes
    op.add_column('invite_codes', sa.Column('assigned_to_username', sa.String(50), nullable=True))
    op.create_index('ix_invite_codes_assigned_to_username', 'invite_codes', ['assigned_to_username'])
    
    # Rename used_count to current_uses
    op.alter_column('invite_codes', 'used_count', new_column_name='current_uses')
    
    # Drop used_by_id column (no longer needed)
    op.drop_column('invite_codes', 'used_by_id')
    
    # Add is_admin column to users (if not already exists)
    # Check if column exists first
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='is_admin'"))
    if result.fetchone() is None:
        op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    # Drop is_admin column
    op.drop_column('users', 'is_admin')
    
    # Add used_by_id column back
    op.add_column('invite_codes', sa.Column('used_by_id', sa.Integer(), nullable=True))
    
    # Rename current_uses back to used_count
    op.alter_column('invite_codes', 'current_uses', new_column_name='used_count')
    
    # Drop assigned_to_username column
    op.drop_index('ix_invite_codes_assigned_to_username', table_name='invite_codes')
    op.drop_column('invite_codes', 'assigned_to_username')
