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


class RefreshTokenFamiliesMigrationTests(unittest.IsolatedAsyncioTestCase):
    """Requires DATABASE_URL to point at a disposable Postgres container —
    never a persistent database. Exercises the upgrade -> downgrade ->
    upgrade cycle for 040_refresh_token_families, including seeding
    pre-migration-style refresh_tokens rows (no token_family_id column at
    all, matching real pre-migration data) to verify the legacy backfill
    assigns each a distinct legacy-<id> family with a matching anchor row."""

    async def test_upgrade_backfills_legacy_families_downgrade_removes_everything(self):
        engine = create_async_engine(settings.DATABASE_URL)

        # Explicit target revisions, not relative "-1"/"head" — this test
        # checks 040's own table/columns in isolation and must stay correct
        # regardless of how many later migrations (e.g. 041) get stacked on
        # top; a relative "-1" only undoes whatever the CURRENT head happens
        # to be, which silently stopped undoing 040 once 041 was added
        # (confirmed via a real failure: a prior run of this test, cut short
        # mid-cycle by an unrelated timeout, left the disposable DB stuck at
        # 040 with 041's column missing, breaking every other test in the
        # same run until `alembic upgrade head` was run manually to recover).
        _run_alembic("downgrade", "039_media_assets_and_feedback_reports")  # back to 039: no token_family_id column, no anchor table

        username = f"legacy-migration-{secrets.token_hex(4)}"
        async with engine.begin() as conn:
            user_id = (await conn.execute(
                text(
                    "INSERT INTO users (username, email, password_hash, status, is_active, created_at) "
                    "VALUES (:username, :email, 'x', 'active', true, now()) RETURNING id"
                ),
                {"username": username, "email": f"{username}@example.com"},
            )).scalar_one()

            seeded_ids = []
            for i in range(3):
                token_id = (await conn.execute(
                    text(
                        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at, revoked, mfa_satisfied, created_at) "
                        "VALUES (:user_id, :token_hash, now() + interval '30 days', false, false, now()) RETURNING id"
                    ),
                    {"user_id": user_id, "token_hash": f"{username}-hash-{i}"},
                )).scalar_one()
                seeded_ids.append(token_id)

        _run_alembic("upgrade", "head")  # apply 040 — must backfill the seeded rows above

        async with engine.connect() as conn:
            table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
            self.assertIn("refresh_token_families", table_names)

            rows = (await conn.execute(
                text("SELECT id, token_family_id FROM refresh_tokens WHERE id = ANY(:ids) ORDER BY id"),
                {"ids": seeded_ids},
            )).all()
            self.assertEqual(len(rows), 3)
            family_ids = [row.token_family_id for row in rows]
            self.assertEqual(family_ids, [f"legacy-{tid}" for tid in seeded_ids])
            self.assertEqual(len(set(family_ids)), 3)  # each pre-migration token got its OWN distinct family

            anchor_rows = (await conn.execute(
                text("SELECT token_family_id FROM refresh_token_families WHERE token_family_id = ANY(:fids)"),
                {"fids": family_ids},
            )).all()
            self.assertEqual({row.token_family_id for row in anchor_rows}, set(family_ids))

            # NOT NULL constraint actually applied, not left nullable.
            columns = await conn.run_sync(
                lambda sync_conn: {c["name"]: c for c in inspect(sync_conn).get_columns("refresh_tokens")}
            )
            self.assertFalse(columns["token_family_id"]["nullable"])

            await conn.execute(text("DELETE FROM refresh_tokens WHERE id = ANY(:ids)"), {"ids": seeded_ids})
            await conn.execute(text("DELETE FROM refresh_token_families WHERE token_family_id = ANY(:fids)"), {"fids": family_ids})
            await conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
            await conn.commit()

        _run_alembic("downgrade", "039_media_assets_and_feedback_reports")

        async with engine.connect() as conn:
            table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
            self.assertNotIn("refresh_token_families", table_names)
            columns = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_columns("refresh_tokens"))
            column_names = {c["name"] for c in columns}
            for lineage_column in ("token_family_id", "parent_token_id", "replaced_by_token_id", "reuse_detected_at"):
                self.assertNotIn(lineage_column, column_names)

        _run_alembic("upgrade", "head")  # leave the DB at head for subsequent tests in the suite
        await engine.dispose()


if __name__ == "__main__":
    unittest.main()
