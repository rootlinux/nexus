"""webauthn_credentials

Revision ID: 025_webauthn_credentials
Revises: 024_phase5_account_session_hardening
Create Date: 2026-04-08 23:00:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "025_webauthn_credentials"
down_revision: Union[str, None] = "024_phase5_account_session_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webauthn_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_id", name="uq_webauthn_credentials_credential_id"),
    )
    op.create_index("ix_webauthn_credentials_id", "webauthn_credentials", ["id"], unique=False)
    op.create_index(
        "ix_webauthn_credentials_user_id", "webauthn_credentials", ["user_id"], unique=False
    )
    op.create_index(
        "ix_webauthn_credentials_credential_id",
        "webauthn_credentials",
        ["credential_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_webauthn_credentials_credential_id", table_name="webauthn_credentials")
    op.drop_index("ix_webauthn_credentials_user_id", table_name="webauthn_credentials")
    op.drop_index("ix_webauthn_credentials_id", table_name="webauthn_credentials")
    op.drop_table("webauthn_credentials")
