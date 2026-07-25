from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "038_admin_audit_service_context.py"


class AdminAuditServiceContextMigrationTests(unittest.TestCase):
    def test_migration_file_exists(self):
        self.assertTrue(MIGRATION.exists())

    def test_upgrade_adds_columns_with_backward_compatible_default(self):
        contents = MIGRATION.read_text()
        self.assertIn('sa.Column("actor_type", sa.String(20), nullable=False, server_default="user")', contents)
        self.assertIn('sa.Column("service_principal_id", sa.String(100), nullable=True)', contents)
        self.assertIn('sa.Column("auth_scopes"', contents)
        # server_default="user" means every existing (pre-migration, human-actor) row is
        # backfilled as actor_type='user' without a separate UPDATE statement or any risk
        # of a NULL actor_type on rows that predate this migration.
        self.assertIn('server_default="user"', contents)

    def test_downgrade_drops_exactly_the_columns_the_upgrade_added(self):
        contents = MIGRATION.read_text()
        downgrade_section = contents.split("def downgrade")[1]
        self.assertIn('op.drop_column("admin_audit_logs", "auth_scopes")', downgrade_section)
        self.assertIn('op.drop_column("admin_audit_logs", "service_principal_id")', downgrade_section)
        self.assertIn('op.drop_column("admin_audit_logs", "actor_type")', downgrade_section)
        # Downgrade must not touch actor_role, actor_user_id, or any other pre-existing
        # column — this migration is additive-only, so rollback should be too.
        self.assertNotIn('op.drop_column("admin_audit_logs", "actor_role")', downgrade_section)
        self.assertNotIn('op.drop_column("admin_audit_logs", "actor_user_id")', downgrade_section)

    def test_down_revision_chains_from_the_current_head(self):
        contents = MIGRATION.read_text()
        self.assertIn('down_revision: Union[str, None] = "037_invite_created_by_nullable"', contents)


if __name__ == "__main__":
    unittest.main()
