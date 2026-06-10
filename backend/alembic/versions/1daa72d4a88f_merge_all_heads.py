"""merge_all_heads

Revision ID: 1daa72d4a88f
Revises: 004_add_refresh_tokens, 9add37080917
Create Date: 2026-03-23 15:20:58.022736

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1daa72d4a88f'
down_revision: Union[str, None] = ('004_add_refresh_tokens', '9add37080917')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass