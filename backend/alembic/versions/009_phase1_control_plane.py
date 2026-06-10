"""Phase 1 control plane foundations

Revision ID: 009_phase1_control_plane
Revises: 008_simplify_invites_for_beta
Create Date: 2026-03-26 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "009_phase1_control_plane"
down_revision: Union[str, None] = "008_simplify_invites_for_beta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    admin_role_enum = postgresql.ENUM(
        "super_admin",
        "invite_admin",
        "moderator",
        "support_admin",
        name="adminrole",
    )
    admin_role_enum.create(bind, checkfirst=True)

    if not _has_column(inspector, "users", "admin_role"):
        op.add_column(
            "users",
            sa.Column(
                "admin_role",
                sa.Enum(
                    "super_admin",
                    "invite_admin",
                    "moderator",
                    "support_admin",
                    name="adminrole",
                ),
                nullable=True,
            ),
        )
        op.create_index("ix_users_admin_role", "users", ["admin_role"], unique=False)

    op.execute(sa.text("UPDATE users SET admin_role = 'super_admin' WHERE is_admin = TRUE AND admin_role IS NULL"))

    if "admin_audit_logs" not in inspector.get_table_names():
        op.create_table(
            "admin_audit_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("actor_role", sa.String(length=50), nullable=True),
            sa.Column("action", sa.String(length=100), nullable=False),
            sa.Column("target_type", sa.String(length=50), nullable=True),
            sa.Column("target_id", sa.String(length=100), nullable=True),
            sa.Column("before_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("after_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("request_id", sa.String(length=64), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("session_id", sa.String(length=128), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_id ON admin_audit_logs (id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_actor_user_id ON admin_audit_logs (actor_user_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_actor_role ON admin_audit_logs (actor_role)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_action ON admin_audit_logs (action)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_target_type ON admin_audit_logs (target_type)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_request_id ON admin_audit_logs (request_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_session_id ON admin_audit_logs (session_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_created_at ON admin_audit_logs (created_at)"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "admin_audit_logs" in inspector.get_table_names():
        op.drop_index("ix_admin_audit_logs_created_at", table_name="admin_audit_logs")
        op.drop_index("ix_admin_audit_logs_session_id", table_name="admin_audit_logs")
        op.drop_index("ix_admin_audit_logs_request_id", table_name="admin_audit_logs")
        op.drop_index("ix_admin_audit_logs_target_type", table_name="admin_audit_logs")
        op.drop_index("ix_admin_audit_logs_action", table_name="admin_audit_logs")
        op.drop_index("ix_admin_audit_logs_actor_role", table_name="admin_audit_logs")
        op.drop_index("ix_admin_audit_logs_actor_user_id", table_name="admin_audit_logs")
        op.drop_index("ix_admin_audit_logs_id", table_name="admin_audit_logs")
        op.drop_table("admin_audit_logs")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "users", "admin_role"):
        op.drop_index("ix_users_admin_role", table_name="users")
        op.drop_column("users", "admin_role")

    admin_role_enum = postgresql.ENUM(
        "super_admin",
        "invite_admin",
        "moderator",
        "support_admin",
        name="adminrole",
    )
    admin_role_enum.drop(bind, checkfirst=True)
