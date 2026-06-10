"""add_follows_index_for_discover

Revision ID: 035_add_follows_index_for_discover
Revises: 034_waitlist_applications
Create Date: 2026-04-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "035_add_follows_index_for_discover"
down_revision: Union[str, None] = "034_waitlist_applications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('idx_follows_follower', 'follows', ['follower_id'], if_not_exists=True)
    op.create_index('idx_follows_following', 'follows', ['following_id'], if_not_exists=True)


def downgrade() -> None:
    op.drop_index('idx_follows_follower', table_name='follows')
    op.drop_index('idx_follows_following', table_name='follows')
