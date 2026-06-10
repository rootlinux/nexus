"""staff_permissions_phase1

Revision ID: 019_staff_permissions_phase1
Revises: 018_refresh_token_device_fingerprint
Create Date: 2026-04-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "019_staff_permissions_phase1"
down_revision: Union[str, None] = "018_refresh_token_device_fingerprint"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    staff_role_enum = postgresql.ENUM("super_admin", "admin", "moderator", name="staffrole", create_type=False)
    staff_role_enum.create(bind, checkfirst=True)

    op.create_table(
        "staff_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", staff_role_enum, nullable=False),
        sa.Column("can_create_invites", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("invite_quota_monthly", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("can_view_moderation_queue", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_moderate_posts", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_manage_invites", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_manage_users", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_suspend_users", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_ban_users", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_manage_moderators", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_reset_passwords", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_revoke_sessions", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_create_wave_campaigns", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_staff_permissions_user_id"),
    )
    op.create_index("ix_staff_permissions_role", "staff_permissions", ["role"], unique=False)
    op.create_index("ix_staff_permissions_updated_by_user_id", "staff_permissions", ["updated_by_user_id"], unique=False)
    op.create_check_constraint(
        "ck_staff_permissions_invite_quota_monthly_range",
        "staff_permissions",
        "(invite_quota_monthly IS NULL OR (invite_quota_monthly >= 0 AND invite_quota_monthly <= 500))",
    )
    op.create_check_constraint(
        "ck_staff_permissions_moderator_cannot_manage_staff",
        "staff_permissions",
        "(role <> 'moderator'::staffrole OR can_manage_moderators = FALSE)",
    )

    op.execute(
        sa.text(
            """
            INSERT INTO staff_permissions (
                user_id,
                role,
                can_create_invites,
                invite_quota_monthly,
                can_view_moderation_queue,
                can_moderate_posts,
                can_manage_invites,
                can_manage_users,
                can_suspend_users,
                can_ban_users,
                can_manage_moderators,
                can_reset_passwords,
                can_revoke_sessions,
                can_create_wave_campaigns,
                updated_by_user_id,
                created_at,
                updated_at
            )
            SELECT
                users.id,
                CASE
                    WHEN users.admin_role = 'moderator' THEN 'moderator'::staffrole
                    WHEN users.admin_role = 'super_admin' OR users.is_admin = TRUE THEN 'super_admin'::staffrole
                    ELSE 'admin'::staffrole
                END,
                CASE
                    WHEN users.admin_role = 'moderator' THEN FALSE
                    ELSE TRUE
                END,
                CASE
                    WHEN users.admin_role = 'moderator' THEN 0
                    ELSE NULL
                END,
                TRUE,
                TRUE,
                CASE
                    WHEN users.admin_role = 'moderator' THEN FALSE
                    ELSE TRUE
                END,
                CASE
                    WHEN users.admin_role = 'moderator' THEN FALSE
                    ELSE TRUE
                END,
                CASE
                    WHEN users.admin_role = 'moderator' THEN FALSE
                    ELSE TRUE
                END,
                CASE
                    WHEN users.admin_role = 'moderator' THEN FALSE
                    ELSE TRUE
                END,
                CASE
                    WHEN users.admin_role = 'moderator' THEN FALSE
                    ELSE TRUE
                END,
                FALSE,
                FALSE,
                FALSE,
                NULL,
                NOW(),
                NOW()
            FROM users
            WHERE
                (users.is_admin = TRUE OR users.admin_role IS NOT NULL)
                AND NOT EXISTS (
                    SELECT 1 FROM staff_permissions WHERE staff_permissions.user_id = users.id
                )
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE users
            SET
                is_admin = TRUE,
                admin_role = CASE
                    WHEN staff_permissions.role = 'super_admin' THEN 'super_admin'::adminrole
                    WHEN staff_permissions.role = 'moderator' THEN 'moderator'::adminrole
                    ELSE 'invite_admin'::adminrole
                END
            FROM staff_permissions
            WHERE users.id = staff_permissions.user_id
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET
                is_admin = FALSE,
                admin_role = NULL
            WHERE users.id IN (
                SELECT user_id FROM staff_permissions
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE users
            SET
                is_admin = TRUE,
                admin_role = CASE
                    WHEN staff_permissions.role = 'super_admin' THEN 'super_admin'::adminrole
                    WHEN staff_permissions.role = 'moderator' THEN 'moderator'::adminrole
                    ELSE 'invite_admin'::adminrole
                END
            FROM staff_permissions
            WHERE users.id = staff_permissions.user_id
            """
        )
    )
    op.drop_constraint("ck_staff_permissions_moderator_cannot_manage_staff", "staff_permissions", type_="check")
    op.drop_constraint("ck_staff_permissions_invite_quota_monthly_range", "staff_permissions", type_="check")
    op.drop_index("ix_staff_permissions_updated_by_user_id", table_name="staff_permissions")
    op.drop_index("ix_staff_permissions_role", table_name="staff_permissions")
    op.drop_table("staff_permissions")

    bind = op.get_bind()
    staff_role_enum = postgresql.ENUM("super_admin", "admin", "moderator", name="staffrole", create_type=False)
    staff_role_enum.drop(bind, checkfirst=True)
