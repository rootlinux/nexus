"""email_canonicalization

Revision ID: 023_email_canonicalization
Revises: 022_phase4_account_security
Create Date: 2026-04-08 18:00:00.000000
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "023_email_canonicalization"
down_revision: Union[str, None] = "022_phase4_account_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate_rows = connection.execute(
        sa.text(
            """
            SELECT LOWER(TRIM(email)) AS normalized_email
            FROM users
            GROUP BY LOWER(TRIM(email))
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if duplicate_rows:
        raise RuntimeError("Cannot canonicalize user emails while case-variant duplicates exist")

    op.execute(sa.text("UPDATE users SET email = LOWER(TRIM(email)) WHERE email <> LOWER(TRIM(email))"))
    op.execute(
        sa.text(
            "UPDATE email_verification_tokens SET email = LOWER(TRIM(email)) "
            "WHERE email <> LOWER(TRIM(email))"
        )
    )
    op.execute(
        sa.text(
            "UPDATE password_reset_tokens SET email = LOWER(TRIM(email)) "
            "WHERE email <> LOWER(TRIM(email))"
        )
    )


def downgrade() -> None:
    pass
