from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "024_phase5_account_session_hardening.py"


class Phase5AccountSecurityMigrationTests(unittest.TestCase):
    def test_migration_file_exists(self):
        self.assertTrue(MIGRATION.exists())

    def test_migration_declares_email_change_tokens_and_refresh_session_columns(self):
        contents = MIGRATION.read_text()
        self.assertIn('"email_change_tokens"', contents)
        self.assertIn('"pending_email"', contents)
        self.assertIn('"last_used_at"', contents)
        self.assertIn('"device_label"', contents)
        self.assertIn("UPDATE refresh_tokens SET last_used_at = created_at", contents)


if __name__ == "__main__":
    unittest.main()
