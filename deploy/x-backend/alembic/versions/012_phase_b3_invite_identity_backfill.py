"""phase_b3_invite_identity_backfill

Revision ID: 012_phase_b3_identity
Revises: 011_moderation_notifications
Create Date: 2026-03-27 13:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "012_phase_b3_identity"
down_revision: Union[str, None] = "011_moderation_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BACKFILL_NOTE = "system_backfill_phase_b3"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            WITH usable_invite_counts AS (
                SELECT
                    users.id AS user_id,
                    GREATEST(
                        3 - COUNT(invite_codes.id) FILTER (
                            WHERE invite_codes.is_active = TRUE
                              AND invite_codes.current_uses < invite_codes.max_uses
                              AND invite_codes.used_by_user_id IS NULL
                              AND invite_codes.used_at IS NULL
                              AND (invite_codes.expires_at IS NULL OR invite_codes.expires_at >= NOW())
                        ),
                        0
                    )::int AS invites_needed
                FROM users
                LEFT JOIN invite_codes
                    ON invite_codes.assigned_to_user_id = users.id
                WHERE users.is_active = TRUE
                  AND users.status = 'active'
                GROUP BY users.id
            )
            INSERT INTO invite_codes (
                code,
                invite_type,
                created_by_id,
                internal_note,
                assigned_to_user_id,
                assigned_to_username,
                max_uses,
                current_uses,
                used_by_user_id,
                used_at,
                expires_at,
                is_active,
                created_at
            )
            SELECT
                md5(random()::text || clock_timestamp()::text || users.id::text || series.n::text),
                'generic',
                users.id,
                :backfill_note,
                users.id,
                users.username,
                1,
                0,
                NULL,
                NULL,
                NULL,
                TRUE,
                NOW()
            FROM usable_invite_counts
            JOIN users ON users.id = usable_invite_counts.user_id
            JOIN LATERAL generate_series(1, usable_invite_counts.invites_needed) AS series(n) ON TRUE
            WHERE usable_invite_counts.invites_needed > 0
            """
        ).bindparams(backfill_note=BACKFILL_NOTE)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM invite_codes
            WHERE internal_note = :backfill_note
              AND current_uses = 0
              AND used_by_user_id IS NULL
              AND used_at IS NULL
            """
        ).bindparams(backfill_note=BACKFILL_NOTE)
    )
