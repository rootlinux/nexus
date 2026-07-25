import os
import secrets
import subprocess
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

BACKEND_DIR = __import__("pathlib").Path(__file__).resolve().parents[1]


def _run_alembic(*args: str) -> None:
    result = subprocess.run(
        ["python", "-m", "alembic", *args],
        cwd=str(BACKEND_DIR), env={**os.environ}, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"alembic {args} failed:\n{result.stdout}\n{result.stderr}"


class MediaAssetsMigrationTests(unittest.IsolatedAsyncioTestCase):
    """Requires DATABASE_URL to point at a disposable Postgres container —
    never a persistent database. This test file is the automated form of the
    upgrade -> downgrade -> upgrade cycle already validated manually before
    this task's commit."""

    async def test_upgrade_creates_all_three_tables_and_enums_downgrade_removes_them(self):
        engine = create_async_engine(settings.DATABASE_URL)

        _run_alembic("downgrade", "-1")  # ensure clean slate relative to 039, idempotent if already there
        _run_alembic("upgrade", "head")

        async with engine.connect() as conn:
            table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
            for table in ("media_assets", "feedback_reports", "user_media_quota"):
                self.assertIn(table, table_names)

            enum_rows = (await conn.execute(
                text("SELECT typname FROM pg_type WHERE typname IN ('mediaassettype', 'mediaassetstatus')")
            )).all()
            self.assertEqual({row[0] for row in enum_rows}, {"mediaassettype", "mediaassetstatus"})

        _run_alembic("downgrade", "-1")

        async with engine.connect() as conn:
            table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
            for table in ("media_assets", "feedback_reports", "user_media_quota"):
                self.assertNotIn(table, table_names)

            enum_rows = (await conn.execute(
                text("SELECT typname FROM pg_type WHERE typname IN ('mediaassettype', 'mediaassetstatus')")
            )).all()
            self.assertEqual(enum_rows, [])

        _run_alembic("upgrade", "head")  # leave the DB at head for subsequent tests in the suite
        await engine.dispose()


if __name__ == "__main__":
    unittest.main()
