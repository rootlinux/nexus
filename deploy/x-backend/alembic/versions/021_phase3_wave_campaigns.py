"""phase3_wave_campaigns

Revision ID: 021_phase3_wave_campaigns
Revises: 020_phase2_secure_admin_actions
Create Date: 2026-04-08 00:00:00.000000
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "021_phase3_wave_campaigns"
down_revision: Union[str, None] = "020_phase2_secure_admin_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invite_campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("public_label", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active_from", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("max_uses_total", sa.Integer(), nullable=True),
        sa.Column("per_user_invite_allowance", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_invite_campaigns_slug"),
        sa.CheckConstraint(
            "(max_uses_total IS NULL OR max_uses_total > 0)",
            name="ck_invite_campaigns_max_uses_total_positive",
        ),
        sa.CheckConstraint(
            "per_user_invite_allowance > 0",
            name="ck_invite_campaigns_per_user_invite_allowance_positive",
        ),
        sa.CheckConstraint(
            "(expires_at IS NULL OR active_from IS NULL OR expires_at > active_from)",
            name="ck_invite_campaigns_window_order",
        ),
    )
    op.create_index("ix_invite_campaigns_is_active", "invite_campaigns", ["is_active"], unique=False)
    op.create_index("ix_invite_campaigns_active_from", "invite_campaigns", ["active_from"], unique=False)
    op.create_index("ix_invite_campaigns_expires_at", "invite_campaigns", ["expires_at"], unique=False)
    op.create_index("ix_invite_campaigns_created_by_user_id", "invite_campaigns", ["created_by_user_id"], unique=False)
    op.create_index("ix_invite_campaigns_updated_by_user_id", "invite_campaigns", ["updated_by_user_id"], unique=False)

    op.add_column("invite_codes", sa.Column("generated_by_user_id", sa.Integer(), nullable=True))
    op.add_column("invite_codes", sa.Column("campaign_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_invite_codes_generated_by_user_id_users",
        "invite_codes",
        "users",
        ["generated_by_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_invite_codes_campaign_id_invite_campaigns",
        "invite_codes",
        "invite_campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_invite_codes_generated_by_user_id", "invite_codes", ["generated_by_user_id"], unique=False)
    op.create_index("ix_invite_codes_campaign_id", "invite_codes", ["campaign_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_invite_codes_campaign_id", table_name="invite_codes")
    op.drop_index("ix_invite_codes_generated_by_user_id", table_name="invite_codes")
    op.drop_constraint("fk_invite_codes_campaign_id_invite_campaigns", "invite_codes", type_="foreignkey")
    op.drop_constraint("fk_invite_codes_generated_by_user_id_users", "invite_codes", type_="foreignkey")
    op.drop_column("invite_codes", "campaign_id")
    op.drop_column("invite_codes", "generated_by_user_id")

    op.drop_index("ix_invite_campaigns_updated_by_user_id", table_name="invite_campaigns")
    op.drop_index("ix_invite_campaigns_created_by_user_id", table_name="invite_campaigns")
    op.drop_index("ix_invite_campaigns_expires_at", table_name="invite_campaigns")
    op.drop_index("ix_invite_campaigns_active_from", table_name="invite_campaigns")
    op.drop_index("ix_invite_campaigns_is_active", table_name="invite_campaigns")
    op.drop_table("invite_campaigns")
