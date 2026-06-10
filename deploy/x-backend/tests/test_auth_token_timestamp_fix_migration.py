from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "029_auth_token_timestamps_timezone_fix.py"


class AuthTokenTimestampFixMigrationTests(unittest.TestCase):
    def test_migration_file_exists(self):
        self.assertTrue(MIGRATION.exists())

    def test_migration_converts_affected_auth_tables_to_timezone_aware_timestamps(self):
        contents = MIGRATION.read_text()
        self.assertIn('"refresh_tokens"', contents)
        self.assertIn('"password_reset_tokens"', contents)
        self.assertIn("sa.DateTime(timezone=True)", contents)
        self.assertIn("AT TIME ZONE 'UTC'", contents)


if __name__ == "__main__":
    unittest.main()
