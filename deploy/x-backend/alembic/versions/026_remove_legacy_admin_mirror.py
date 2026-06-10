"""remove_legacy_admin_mirror

Revision ID: 026_remove_legacy_admin_mirror
Revises: 025_webauthn_credentials
Create Date: 2026-04-09 12:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "026_remove_legacy_admin_mirror"
down_revision: Union[str, None] = "025_webauthn_credentials"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "users", "ix_users_admin_role"):
        op.drop_index("ix_users_admin_role", table_name="users")

    if _has_column(inspector, "users", "admin_role"):
        op.drop_column("users", "admin_role")

    if _has_column(inspector, "users", "is_admin"):
        op.drop_column("users", "is_admin")

    bind.execute(sa.text("DROP TYPE IF EXISTS adminrole"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    bind.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'adminrole') THEN
                    CREATE TYPE adminrole AS ENUM (
                        'super_admin',
                        'invite_admin',
                        'moderator',
                        'support_admin'
                    );
                END IF;
            END
            $$;
            """
        )
    )

    if not _has_column(inspector, "users", "is_admin"):
        op.add_column(
            "users",
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )

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

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "users", "ix_users_admin_role"):
        op.create_index("ix_users_admin_role", "users", ["admin_role"], unique=False)
