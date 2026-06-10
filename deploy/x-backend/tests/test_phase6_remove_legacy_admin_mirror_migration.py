from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "026_remove_legacy_admin_mirror.py"


class TestRemoveLegacyAdminMirrorMigration:
    def test_migration_file_exists(self):
        assert MIGRATION.exists(), "Expected legacy admin mirror removal migration to exist"

    def test_migration_drops_legacy_admin_columns(self):
        content = MIGRATION.read_text()

        assert 'revision: str = "026_remove_legacy_admin_mirror"' in content
        assert 'down_revision: Union[str, None] = "025_webauthn_credentials"' in content
        assert 'op.drop_column("users", "admin_role")' in content
        assert 'op.drop_column("users", "is_admin")' in content
        assert 'DROP TYPE IF EXISTS adminrole' in content

    def test_migration_downgrade_restores_legacy_columns(self):
        content = MIGRATION.read_text()

        assert 'op.add_column(' in content
        assert '"users"' in content
        assert 'sa.Column("is_admin", sa.Boolean()' in content
        assert 'sa.Column(' in content
        assert '"admin_role"' in content
        assert 'op.create_index("ix_users_admin_role", "users", ["admin_role"], unique=False)' in content
