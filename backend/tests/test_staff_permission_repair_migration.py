import importlib.util
from pathlib import Path
import unittest

import sqlalchemy as sa


class _FakeOp:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement):
        sql = str(statement).replace("NOW()", "CURRENT_TIMESTAMP")
        return self.connection.execute(sa.text(sql))


class StaffPermissionRepairMigrationTests(unittest.TestCase):
    def test_upgrade_backfills_stale_staff_rows_with_role_defaults(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    CREATE TABLE staff_permissions (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        role VARCHAR(50) NOT NULL,
                        can_create_invites BOOLEAN NOT NULL DEFAULT 0,
                        invite_quota_monthly INTEGER,
                        can_view_moderation_queue BOOLEAN NOT NULL DEFAULT 0,
                        can_moderate_posts BOOLEAN NOT NULL DEFAULT 0,
                        can_manage_invites BOOLEAN NOT NULL DEFAULT 0,
                        can_manage_users BOOLEAN NOT NULL DEFAULT 0,
                        can_suspend_users BOOLEAN NOT NULL DEFAULT 0,
                        can_ban_users BOOLEAN NOT NULL DEFAULT 0,
                        can_manage_moderators BOOLEAN NOT NULL DEFAULT 0,
                        can_reset_passwords BOOLEAN NOT NULL DEFAULT 0,
                        can_revoke_sessions BOOLEAN NOT NULL DEFAULT 0,
                        can_create_wave_campaigns BOOLEAN NOT NULL DEFAULT 0,
                        updated_by_user_id INTEGER,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                    """
                )
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO staff_permissions (
                        id, user_id, role, can_create_invites, invite_quota_monthly,
                        can_view_moderation_queue, can_moderate_posts, can_manage_invites,
                        can_manage_users, can_suspend_users, can_ban_users,
                        can_manage_moderators, can_reset_passwords, can_revoke_sessions,
                        can_create_wave_campaigns, updated_by_user_id, created_at, updated_at
                    ) VALUES
                    (1, 10, 'super_admin', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    (2, 11, 'admin', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 99, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    (3, 12, 'moderator', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                )
            )

            migration_path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "028_repair_stale_staff_permission_defaults.py"
            spec = importlib.util.spec_from_file_location("staff_permission_repair_migration", migration_path)
            migration = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(migration)

            original_op = migration.op
            try:
                migration.op = _FakeOp(connection)
                migration.upgrade()
            finally:
                migration.op = original_op

            rows = connection.execute(
                sa.text(
                    """
                    SELECT
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
                        can_manage_moderators
                    FROM staff_permissions
                    ORDER BY user_id
                    """
                )
            ).fetchall()

            self.assertEqual(
                rows,
                [
                    (10, "super_admin", 1, None, 1, 1, 1, 1, 1, 1, 1),
                    (11, "admin", 0, 0, 0, 0, 0, 0, 0, 0, 0),
                    (12, "moderator", 0, 0, 1, 1, 0, 0, 0, 0, 0),
                ],
            )


if __name__ == "__main__":
    unittest.main()
