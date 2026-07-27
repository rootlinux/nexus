import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_refresh_token, hash_refresh_token
from app.main import app
from app.models.admin_audit_log import AdminAuditLog
from app.models.refresh_token import RefreshToken
from app.models.refresh_token_family import RefreshTokenFamily
from tests.media_test_support import create_test_user

BASELINE_HEADERS = {
    "user-agent": "TestClient/1.0 (Baseline; Macintosh)",
    "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "gzip",
    "sec-ch-ua-platform": '"macOS"',
}


class DeviceFingerprintSoftSignalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        temp_engine = create_async_engine(settings.DATABASE_URL)
        try:
            temp_sf = async_sessionmaker(temp_engine, expire_on_commit=False)
            async with temp_sf() as session:
                user = await create_test_user(session)
                await session.commit()
                self.user_id = user.id
        finally:
            await temp_engine.dispose()

        async def override_db():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        self._rate_limit_patch = patch("app.api.routes.auth.enforce_rate_limits", new=AsyncMock())
        self._rate_limit_patch.start()

    async def asyncTearDown(self):
        self._rate_limit_patch.stop()
        app.dependency_overrides.clear()
        await self.engine.dispose()

    async def _seed_root_token(self) -> str:
        # device_fingerprint=None so the FIRST refresh, whatever headers it
        # carries, never trips a mismatch — matches how a freshly-issued
        # token from a real login behaves before any fingerprint is on file.
        family_id = str(uuid4())
        db = self.session_factory()
        try:
            db.add(RefreshTokenFamily(token_family_id=family_id))
            await db.flush()
            raw = create_refresh_token()
            record = RefreshToken(
                user_id=self.user_id, token_hash=hash_refresh_token(raw),
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                revoked=False, mfa_satisfied=False, last_used_at=datetime.now(timezone.utc),
                token_family_id=family_id, parent_token_id=None, device_fingerprint=None,
            )
            db.add(record)
            await db.commit()
            return raw
        finally:
            await db.close()

    async def _create_chain(self, length: int) -> tuple[str, list[dict]]:
        family_id = str(uuid4())
        chain: list[dict] = []
        db = self.session_factory()
        try:
            db.add(RefreshTokenFamily(token_family_id=family_id))
            await db.flush()
            parent_id = None
            for _ in range(length):
                raw = create_refresh_token()
                token_hash = hash_refresh_token(raw)
                record = RefreshToken(
                    user_id=self.user_id, token_hash=token_hash,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                    revoked=False, mfa_satisfied=False, last_used_at=datetime.now(timezone.utc),
                    token_family_id=family_id, parent_token_id=parent_id,
                    device_fingerprint=None,
                )
                db.add(record)
                await db.flush()
                chain.append({"id": record.id, "raw": raw})
                parent_id = record.id
            for i in range(length - 1):
                prev = await db.get(RefreshToken, chain[i]["id"])
                prev.revoked = True
                prev.replaced_by_token_id = chain[i + 1]["id"]
            await db.commit()
        finally:
            await db.close()
        return family_id, chain

    async def _audit_actions_for_token_hash(self, raw_token: str) -> list[str]:
        db = self.session_factory()
        try:
            token_hash = hash_refresh_token(raw_token)
            token = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
            rows = (await db.scalars(
                select(AdminAuditLog.action).where(AdminAuditLog.session_id == str(token.id))
            )).all()
            return list(rows)
        finally:
            await db.close()

    async def test_accept_language_change_alone_gets_200_and_logs_soft_signal(self):
        root_raw = await self._seed_root_token()

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            first = await client.post(
                "/api/auth/refresh", json={"refresh_token": root_raw}, headers=BASELINE_HEADERS,
            )
            self.assertEqual(first.status_code, 200)
            baseline_issued_token = first.json()["refresh_token"]

            changed_headers = {**BASELINE_HEADERS, "accept-language": "fr-FR,fr;q=0.9"}
            second = await client.post(
                "/api/auth/refresh", json={"refresh_token": baseline_issued_token}, headers=changed_headers,
            )

        self.assertEqual(second.status_code, 200)  # session continues despite the fingerprint mismatch
        audit_actions = await self._audit_actions_for_token_hash(baseline_issued_token)
        self.assertIn("refresh.fingerprint_changed", audit_actions)
        self.assertNotIn("refresh.reuse_detected", audit_actions)
        self.assertNotIn("refresh.revoked_token_reuse", audit_actions)

    async def test_fully_different_user_agent_still_gets_200(self):
        root_raw = await self._seed_root_token()

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            first = await client.post(
                "/api/auth/refresh", json={"refresh_token": root_raw}, headers=BASELINE_HEADERS,
            )
            self.assertEqual(first.status_code, 200)
            baseline_issued_token = first.json()["refresh_token"]

            totally_different_headers = {
                "user-agent": "Mozilla/5.0 (completely different browser and OS)",
                "accept-language": "ja-JP,ja;q=0.9",
                "accept-encoding": "br",
                "sec-ch-ua-platform": '"Windows"',
            }
            second = await client.post(
                "/api/auth/refresh", json={"refresh_token": baseline_issued_token}, headers=totally_different_headers,
            )

        self.assertEqual(second.status_code, 200)
        audit_actions = await self._audit_actions_for_token_hash(baseline_issued_token)
        self.assertIn("refresh.fingerprint_changed", audit_actions)

    async def test_replay_detection_still_fires_independent_of_fingerprint_mismatch(self):
        # root (already rotated, revoked) -> current valid — with device
        # fingerprints left unset entirely, so ANY headers would "match" (no
        # fingerprint on file means no mismatch is even possible) — this
        # isolates that replay detection is a hard signal on its own,
        # triggered purely by db_token.revoked + replaced_by_token_id, with
        # zero dependency on fingerprint state either way.
        family_id, chain = await self._create_chain(2)
        root, _current = chain

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await client.post(
                "/api/auth/refresh",
                json={"refresh_token": root["raw"]},
                headers={"user-agent": "Whatever/Anything", "accept-language": "xx"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Session invalidated. Please log in again.")

        db = self.session_factory()
        try:
            rows = (await db.scalars(
                select(AdminAuditLog.action).where(AdminAuditLog.session_id == str(root["id"]))
            )).all()
        finally:
            await db.close()
        self.assertIn("refresh.reuse_detected", rows)


if __name__ == "__main__":
    unittest.main()
