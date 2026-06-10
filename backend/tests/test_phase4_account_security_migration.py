from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "022_phase4_account_security.py"
CANONICALIZATION_MIGRATION = ROOT / "alembic" / "versions" / "023_email_canonicalization.py"


class Phase4AccountSecurityMigrationTests(unittest.TestCase):
    def test_migration_file_exists(self):
        self.assertTrue(MIGRATION.exists())
        self.assertTrue(CANONICALIZATION_MIGRATION.exists())

    def test_migration_declares_security_tables_and_backfill(self):
        contents = MIGRATION.read_text()
        self.assertIn('"email_verified_at"', contents)
        self.assertIn('"email_verification_tokens"', contents)
        self.assertIn('"password_reset_tokens"', contents)
        self.assertIn("UPDATE users SET email_verified_at", contents)

    def test_email_canonicalization_migration_backfills_and_guards_duplicates(self):
        contents = CANONICALIZATION_MIGRATION.read_text()
        self.assertIn("LOWER(TRIM(email))", contents)
        self.assertIn("case-variant duplicates", contents)
        self.assertIn("UPDATE users SET email = LOWER(TRIM(email))", contents)
        self.assertIn("UPDATE email_verification_tokens SET email = LOWER(TRIM(email))", contents)
        self.assertIn("UPDATE password_reset_tokens SET email = LOWER(TRIM(email))", contents)


if __name__ == "__main__":
    unittest.main()
