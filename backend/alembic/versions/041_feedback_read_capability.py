"""Add can_view_feedback capability column to staff_permissions

Revision ID: 041_feedback_read_capability
Revises: 040_refresh_token_families
Create Date: 2026-07-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "041_feedback_read_capability"
down_revision: Union[str, None] = "040_refresh_token_families"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "staff_permissions",
        sa.Column("can_view_feedback", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Preserves today's de facto behavior for admin/super_admin (who could
    # already reach feedback attachments via require_admin_session).
    # Intentionally narrows moderator access — moderators keep False, losing
    # the default access they technically have today. Flagged in the plan:
    # a real behavior change worth confirming against actual role
    # assignments before this deploys.
    op.execute(
        "UPDATE staff_permissions SET can_view_feedback = true WHERE role IN ('admin', 'super_admin')"
    )


def downgrade() -> None:
    op.drop_column("staff_permissions", "can_view_feedback")
