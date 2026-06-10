"""Add invite usage audit table and normalize invite usage counters

Revision ID: 007_inv_usage_audit
Revises: 006_mod_inv_trace
Create Date: 2026-03-25 14:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "007_inv_usage_audit"
down_revision: Union[str, None] = "006_mod_inv_trace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    invite_type_enum = postgresql.ENUM("generic", "personal", "referral", name="invitetype")
    invite_type_enum.create(bind, checkfirst=True)

    if _has_column(inspector, "invite_codes", "used_count") and not _has_column(inspector, "invite_codes", "current_uses"):
        op.alter_column("invite_codes", "used_count", new_column_name="current_uses")

    if _has_column(inspector, "invite_codes", "used_by_id") and not _has_column(inspector, "invite_codes", "used_by_user_id"):
        op.alter_column("invite_codes", "used_by_id", new_column_name="used_by_user_id")

    inspector = sa.inspect(bind)

    if not _has_column(inspector, "invite_codes", "invite_type"):
        op.add_column(
            "invite_codes",
            sa.Column(
                "invite_type",
                sa.Enum("generic", "personal", "referral", name="invitetype"),
                nullable=False,
                server_default="generic",
            ),
        )

    if not _has_column(inspector, "invite_codes", "assigned_to_username"):
        op.add_column("invite_codes", sa.Column("assigned_to_username", sa.String(length=50), nullable=True))

    if not _has_column(inspector, "invite_codes", "inviter_id"):
        op.add_column("invite_codes", sa.Column("inviter_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_invite_codes_inviter_id_users",
            "invite_codes",
            "users",
            ["inviter_id"],
            ["id"],
        )

    if not _has_column(inspector, "invite_codes", "current_uses"):
        op.add_column(
            "invite_codes",
            sa.Column("current_uses", sa.Integer(), nullable=False, server_default="0"),
        )

    if not _has_column(inspector, "invite_codes", "used_by_user_id"):
        op.add_column("invite_codes", sa.Column("used_by_user_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_invite_codes_used_by_user_id_users",
            "invite_codes",
            "users",
            ["used_by_user_id"],
            ["id"],
        )

    if not _has_column(inspector, "invite_codes", "used_at"):
        op.add_column("invite_codes", sa.Column("used_at", sa.DateTime(), nullable=True))

    op.execute(sa.text("UPDATE invite_codes SET invite_type = 'generic' WHERE invite_type IS NULL"))
    op.execute(sa.text("UPDATE invite_codes SET current_uses = 0 WHERE current_uses IS NULL"))

    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_invite_codes_invite_type ON invite_codes (invite_type)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_invite_codes_assigned_to_username ON invite_codes (assigned_to_username)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_invite_codes_inviter_id ON invite_codes (inviter_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_invite_codes_used_by_user_id ON invite_codes (used_by_user_id)"))

    op.create_table(
        "invite_usages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invite_id", sa.Integer(), nullable=False),
        sa.Column("used_by_user_id", sa.Integer(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["invite_id"], ["invite_codes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("used_by_user_id", name="uq_invite_usages_used_by_user_id"),
    )
    op.create_index("ix_invite_usages_id", "invite_usages", ["id"], unique=False)
    op.create_index("ix_invite_usages_invite_id", "invite_usages", ["invite_id"], unique=False)
    op.create_index("ix_invite_usages_used_at", "invite_usages", ["used_at"], unique=False)
    op.create_index("ix_invite_usages_used_by_user_id", "invite_usages", ["used_by_user_id"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO invite_usages (invite_id, used_by_user_id, used_at)
            SELECT
                users.invite_id_used,
                users.id,
                COALESCE(invite_codes.used_at, users.created_at, NOW())
            FROM users
            JOIN invite_codes ON invite_codes.id = users.invite_id_used
            WHERE users.invite_id_used IS NOT NULL
            ON CONFLICT (used_by_user_id) DO NOTHING
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE invite_codes
            SET current_uses = counts.usage_count
            FROM (
                SELECT invite_id, COUNT(*)::int AS usage_count
                FROM invite_usages
                GROUP BY invite_id
            ) AS counts
            WHERE invite_codes.id = counts.invite_id
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE invite_codes
            SET current_uses = 0,
                used_by_user_id = NULL,
                used_at = NULL
            WHERE invite_codes.id NOT IN (
                SELECT DISTINCT invite_id FROM invite_usages
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE invite_codes
            SET used_by_user_id = latest.used_by_user_id,
                used_at = latest.used_at
            FROM (
                SELECT DISTINCT ON (invite_id)
                    invite_id,
                    used_by_user_id,
                    used_at
                FROM invite_usages
                ORDER BY invite_id, used_at DESC, id DESC
            ) AS latest
            WHERE invite_codes.id = latest.invite_id
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE invite_codes
            SET is_active = CASE
                WHEN current_uses >= max_uses THEN FALSE
                ELSE is_active
            END
            """
        )
    )

    op.alter_column("invite_codes", "invite_type", server_default=None)
    op.alter_column("invite_codes", "current_uses", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_invite_usages_used_by_user_id", table_name="invite_usages")
    op.drop_index("ix_invite_usages_used_at", table_name="invite_usages")
    op.drop_index("ix_invite_usages_invite_id", table_name="invite_usages")
    op.drop_index("ix_invite_usages_id", table_name="invite_usages")
    op.drop_table("invite_usages")
