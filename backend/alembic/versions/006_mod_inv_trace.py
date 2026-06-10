"""Add moderation and invite traceability fields

Revision ID: 006_mod_inv_trace
Revises: 005_add_display_name
Create Date: 2026-03-25

This migration adds:
1. User moderation fields (status, banned_at, ban_reason, banned_by_user_id)
2. Invite traceability fields (invited_by_user_id, invite_id_used)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum


# revision identifiers, used by Alembic.
revision = '006_mod_inv_trace'
down_revision = '005_add_display_name'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type for user status
    user_status_enum = sa.Enum('active', 'suspended', 'banned', name='userstatus', create_type=False)
    user_status_enum.create(op.get_bind(), checkfirst=True)
    
    # Add moderation fields to users table
    op.add_column('users', Column('status', user_status_enum, nullable=False, server_default='active'))
    op.add_column('users', Column('banned_at', DateTime, nullable=True))
    op.add_column('users', Column('ban_reason', String(500), nullable=True))
    op.add_column('users', Column('banned_by_user_id', Integer, ForeignKey('users.id'), nullable=True))
    
    # Add invite traceability fields to users table
    op.add_column('users', Column('invited_by_user_id', Integer, ForeignKey('users.id'), nullable=True))
    op.add_column('users', Column('invite_id_used', Integer, ForeignKey('invite_codes.id'), nullable=True))
    
    # Add indexes for better query performance
    op.create_index('ix_users_status', 'users', ['status'])
    op.create_index('ix_users_invited_by_user_id', 'users', ['invited_by_user_id'])
    op.create_index('ix_users_invite_id_used', 'users', ['invite_id_used'])
    op.create_index('ix_users_banned_by_user_id', 'users', ['banned_by_user_id'])


def downgrade() -> None:
    # Remove indexes
    op.drop_index('ix_users_banned_by_user_id', table_name='users')
    op.drop_index('ix_users_invite_id_used', table_name='users')
    op.drop_index('ix_users_invited_by_user_id', table_name='users')
    op.drop_index('ix_users_status', table_name='users')
    
    # Remove columns
    op.drop_column('users', 'invite_id_used')
    op.drop_column('users', 'invited_by_user_id')
    op.drop_column('users', 'banned_by_user_id')
    op.drop_column('users', 'ban_reason')
    op.drop_column('users', 'banned_at')
    op.drop_column('users', 'status')
    
    # Drop enum type
    user_status_enum = sa.Enum('active', 'suspended', 'banned', name='userstatus')
    user_status_enum.drop(op.get_bind(), checkfirst=True)
