"""moderation_notifications

Revision ID: 011_moderation_notifications
Revises: 010_profile_expansion
Create Date: 2026-03-26 15:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "011_moderation_notifications"
down_revision: Union[str, None] = "010_profile_expansion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    user_status_enum = postgresql.ENUM("active", "frozen", "suspended", "banned", name="userstatus")
    user_status_enum.create(bind, checkfirst=True)
    post_status_enum = postgresql.ENUM("visible", "hidden", "deleted", name="postmoderationstatus")
    post_status_enum.create(bind, checkfirst=True)
    notification_type_enum = postgresql.ENUM("like", "repost", "follow", "reply", "mention", name="notificationtype")
    notification_type_enum.create(bind, checkfirst=True)

    post_status_column_enum = postgresql.ENUM(
        "visible",
        "hidden",
        "deleted",
        name="postmoderationstatus",
        create_type=False,
    )
    notification_type_column_enum = postgresql.ENUM(
        "like",
        "repost",
        "follow",
        "reply",
        "mention",
        name="notificationtype",
        create_type=False,
    )

    op.execute(sa.text("ALTER TYPE userstatus ADD VALUE IF NOT EXISTS 'frozen'"))

    op.add_column("users", sa.Column("status_reason", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("status_changed_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("status_changed_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_status_changed_by_user_id_users",
        "users",
        "users",
        ["status_changed_by_user_id"],
        ["id"],
    )
    op.create_index("ix_users_status_changed_by_user_id", "users", ["status_changed_by_user_id"], unique=False)

    op.add_column(
        "posts",
        sa.Column(
            "moderation_status",
            post_status_column_enum,
            nullable=False,
            server_default="visible",
        ),
    )
    op.add_column("posts", sa.Column("moderation_reason", sa.String(length=500), nullable=True))
    op.add_column("posts", sa.Column("moderated_at", sa.DateTime(), nullable=True))
    op.add_column("posts", sa.Column("moderated_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_posts_moderated_by_user_id_users",
        "posts",
        "users",
        ["moderated_by_user_id"],
        ["id"],
    )
    op.create_index("ix_posts_moderation_status", "posts", ["moderation_status"], unique=False)
    op.create_index("ix_posts_moderated_by_user_id", "posts", ["moderated_by_user_id"], unique=False)

    op.create_table(
        "notification_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("push_likes", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("push_replies", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("push_reposts", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("push_mentions", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("push_follows", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("email_likes", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_replies", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_reposts", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_mentions", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_follows", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_notification_settings_id", "notification_settings", ["id"], unique=False)
    op.create_index("ix_notification_settings_user_id", "notification_settings", ["user_id"], unique=True)

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("notification_type", notification_type_column_enum, nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("source_post_id", sa.Integer(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "actor_user_id",
            "notification_type",
            "post_id",
            "source_post_id",
            name="uq_notification_dedupe",
        ),
    )
    op.create_index("ix_notifications_id", "notifications", ["id"], unique=False)
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"], unique=False)
    op.create_index("ix_notifications_actor_user_id", "notifications", ["actor_user_id"], unique=False)
    op.create_index("ix_notifications_notification_type", "notifications", ["notification_type"], unique=False)
    op.create_index("ix_notifications_post_id", "notifications", ["post_id"], unique=False)
    op.create_index("ix_notifications_source_post_id", "notifications", ["source_post_id"], unique=False)
    op.create_index("ix_notifications_read_at", "notifications", ["read_at"], unique=False)
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_read_at", table_name="notifications")
    op.drop_index("ix_notifications_source_post_id", table_name="notifications")
    op.drop_index("ix_notifications_post_id", table_name="notifications")
    op.drop_index("ix_notifications_notification_type", table_name="notifications")
    op.drop_index("ix_notifications_actor_user_id", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_index("ix_notifications_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("ix_notification_settings_user_id", table_name="notification_settings")
    op.drop_index("ix_notification_settings_id", table_name="notification_settings")
    op.drop_table("notification_settings")

    op.drop_index("ix_posts_moderated_by_user_id", table_name="posts")
    op.drop_index("ix_posts_moderation_status", table_name="posts")
    op.drop_constraint("fk_posts_moderated_by_user_id_users", "posts", type_="foreignkey")
    op.drop_column("posts", "moderated_by_user_id")
    op.drop_column("posts", "moderated_at")
    op.drop_column("posts", "moderation_reason")
    op.drop_column("posts", "moderation_status")

    op.drop_index("ix_users_status_changed_by_user_id", table_name="users")
    op.drop_constraint("fk_users_status_changed_by_user_id_users", "users", type_="foreignkey")
    op.drop_column("users", "status_changed_by_user_id")
    op.drop_column("users", "status_changed_at")
    op.drop_column("users", "status_reason")

    bind = op.get_bind()
    post_status_enum = postgresql.ENUM("visible", "hidden", "deleted", name="postmoderationstatus")
    notification_type_enum = postgresql.ENUM("like", "repost", "follow", "reply", "mention", name="notificationtype")
    post_status_enum.drop(bind, checkfirst=True)
    notification_type_enum.drop(bind, checkfirst=True)
