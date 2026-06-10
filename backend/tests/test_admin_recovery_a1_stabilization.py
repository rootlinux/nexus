from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
MIGRATION = ROOT / "alembic" / "versions" / "032_admin_recovery_webauthn_timestamp_fix.py"
COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose.yml"


class AdminRecoveryA1StabilizationTests(unittest.TestCase):
    def test_webauthn_credential_timezone_fix_migration_exists(self):
        self.assertTrue(MIGRATION.exists())

    def test_webauthn_credential_timezone_fix_migration_is_narrow(self):
        contents = MIGRATION.read_text()
        self.assertIn('"webauthn_credentials"', contents)
        self.assertIn('"created_at"', contents)
        self.assertIn('"last_used_at"', contents)
        self.assertIn("timezone_aware=True", contents)
        self.assertIn("AT TIME ZONE 'UTC'", contents)

    def test_compose_passes_admin_recovery_env_vars_to_backend(self):
        contents = COMPOSE_FILE.read_text()
        self.assertIn("ENABLE_ADMIN_WEBAUTHN_RECOVERY", contents)
        self.assertIn("ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER", contents)
        self.assertIn("ENABLE_ADMIN_WEBAUTHN_RECOVERY: ${ENABLE_ADMIN_WEBAUTHN_RECOVERY:-false}", contents)
        self.assertIn(
            "ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER: ${ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER:-}",
            contents,
        )


if __name__ == "__main__":
    unittest.main()
