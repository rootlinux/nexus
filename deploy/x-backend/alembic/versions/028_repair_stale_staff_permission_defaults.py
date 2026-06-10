"""repair_stale_staff_permission_defaults

Revision ID: 028_repair_stale_staff_permission_defaults
Revises: 027_add_mfa_satisfied_to_refresh_tokens
Create Date: 2026-04-10 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "028_repair_stale_staff_permission_defaults"
down_revision: Union[str, None] = "027_add_mfa_satisfied_to_refresh_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE staff_permissions
            SET
                can_create_invites = CASE WHEN role = 'moderator' THEN FALSE ELSE TRUE END,
                invite_quota_monthly = CASE WHEN role = 'moderator' THEN COALESCE(invite_quota_monthly, 0) ELSE NULL END,
                can_view_moderation_queue = TRUE,
                can_moderate_posts = TRUE,
                can_manage_invites = CASE WHEN role = 'moderator' THEN FALSE ELSE TRUE END,
                can_manage_users = CASE WHEN role = 'moderator' THEN FALSE ELSE TRUE END,
                can_suspend_users = CASE WHEN role = 'moderator' THEN FALSE ELSE TRUE END,
                can_ban_users = CASE WHEN role = 'moderator' THEN FALSE ELSE TRUE END,
                can_manage_moderators = CASE WHEN role = 'moderator' THEN FALSE ELSE TRUE END,
                can_reset_passwords = FALSE,
                can_revoke_sessions = FALSE,
                can_create_wave_campaigns = FALSE,
                updated_at = NOW()
            WHERE
                updated_by_user_id IS NULL
                AND can_create_invites = FALSE
                AND can_view_moderation_queue = FALSE
                AND can_moderate_posts = FALSE
                AND can_manage_invites = FALSE
                AND can_manage_users = FALSE
                AND can_suspend_users = FALSE
                AND can_ban_users = FALSE
                AND can_manage_moderators = FALSE
                AND can_reset_passwords = FALSE
                AND can_revoke_sessions = FALSE
                AND can_create_wave_campaigns = FALSE
            """
        )
    )


def downgrade() -> None:
    pass
