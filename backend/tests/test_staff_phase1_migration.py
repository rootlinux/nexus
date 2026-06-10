import importlib
import importlib.util
from pathlib import Path
import unittest

import sqlalchemy as sa


class _FakeOp:
    def __init__(self, connection):
        self.connection = connection
        self.metadata = sa.MetaData()
        self.metadata.reflect(bind=connection)
        self.tables: dict[str, sa.Table] = {}
        self.tables.update(self.metadata.tables)

    def get_bind(self):
        return self.connection

    def create_table(self, name, *columns, **kwargs):
        table = sa.Table(name, self.metadata, *columns, *kwargs.get("constraints", ()))
        table.create(self.connection)
        self.tables[name] = table
        return table

    def create_index(self, name, table_name, columns, unique=False):
        table = self.tables[table_name]
        index = sa.Index(name, *(table.c[column] for column in columns), unique=unique)
        index.create(self.connection)

    def create_check_constraint(self, name, table_name, condition):
        return None

    def drop_constraint(self, name, table_name, type_=None):
        return None

    def drop_index(self, name, table_name=None):
        return None

    def drop_table(self, table_name):
        self.tables[table_name].drop(self.connection)

    def execute(self, statement):
        sql = str(statement)
        sql = sql.replace("::staffrole", "").replace("::adminrole", "")
        sql = sql.replace("NOW()", "CURRENT_TIMESTAMP")
        return self.connection.execute(sa.text(sql))


class _FakeEnum(sa.String):
    def __init__(self, *values, name, **kwargs):
        super().__init__(length=max((len(value) for value in values), default=0) or None)
        self.values = values
        self.name = name

    def create(self, bind, checkfirst=True):
        return None

    def drop(self, bind, checkfirst=True):
        return None


class StaffPhase1MigrationTests(unittest.TestCase):
    def test_migration_upgrade_backfills_staff_permissions(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY,
                        is_admin BOOLEAN NOT NULL DEFAULT 0,
                        admin_role VARCHAR(50)
                    )
                    """
                )
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO users (id, is_admin, admin_role) VALUES
                    (1, 1, NULL),
                    (2, 0, 'super_admin'),
                    (3, 0, 'moderator'),
                    (4, 0, NULL)
                    """
                )
            )

            migration_path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "019_staff_permissions_phase1.py"
            spec = importlib.util.spec_from_file_location("staff_permissions_phase1_migration", migration_path)
            migration = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(migration)
            original_op = migration.op
            original_enum = migration.postgresql.ENUM
            try:
                migration.op = _FakeOp(connection)
                migration.postgresql.ENUM = _FakeEnum
                migration.upgrade()
            finally:
                migration.op = original_op
                migration.postgresql.ENUM = original_enum

            rows = connection.execute(
                sa.text(
                    """
                    SELECT user_id, role, can_manage_moderators, invite_quota_monthly
                    FROM staff_permissions
                    ORDER BY user_id
                    """
                )
            ).fetchall()
            self.assertEqual(
                rows,
                [
                    (1, "super_admin", 1, None),
                    (2, "super_admin", 1, None),
                    (3, "moderator", 0, 0),
                ],
            )

            users = connection.execute(
                sa.text("SELECT id, is_admin, admin_role FROM users ORDER BY id")
            ).fetchall()
            self.assertEqual(
                users,
                [
                    (1, 1, "super_admin"),
                    (2, 1, "super_admin"),
                    (3, 1, "moderator"),
                    (4, 0, None),
                ],
            )


if __name__ == "__main__":
    unittest.main()
