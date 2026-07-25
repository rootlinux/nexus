"""Add service-principal audit context to admin_audit_logs

Revision ID: 038_admin_audit_service_context
Revises: 037_invite_created_by_nullable
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "038_admin_audit_service_context"
down_revision: Union[str, None] = "037_invite_created_by_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows are all human-actor entries, so backfilling actor_type='user'
    # via server_default keeps them semantically correct without a data migration.
    op.add_column(
        "admin_audit_logs",
        sa.Column("actor_type", sa.String(20), nullable=False, server_default="user"),
    )
    op.add_column(
        "admin_audit_logs",
        sa.Column("service_principal_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "admin_audit_logs",
        sa.Column("auth_scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_admin_audit_logs_actor_type", "admin_audit_logs", ["actor_type"]
    )
    op.create_index(
        "ix_admin_audit_logs_service_principal_id",
        "admin_audit_logs",
        ["service_principal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_logs_service_principal_id", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_actor_type", table_name="admin_audit_logs")
    op.drop_column("admin_audit_logs", "auth_scopes")
    op.drop_column("admin_audit_logs", "service_principal_id")
    op.drop_column("admin_audit_logs", "actor_type")
