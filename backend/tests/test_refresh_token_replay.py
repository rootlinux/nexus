import asyncio
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


class RefreshTokenReplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # NullPool: separate concurrent requests through ASGITransport don't
        # guarantee one persistent connection-safe loop (see Task 3/4 handoff
        # entries) — a fresh physical connection per checkout sidesteps that.
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

    async def _create_chain(self, length: int) -> tuple[str, list[dict]]:
        """Builds a family with `length` tokens: root -> child -> ... -> current.
        Every token except the last is revoked with replaced_by_token_id set
        to the next one — exactly what a real rotation chain looks like.
        Returns (token_family_id, [{"id", "raw", "hash"}, ...]) oldest-first."""
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
                    revoked=False, mfa_satisfied=False,
                    last_used_at=datetime.now(timezone.utc),
                    token_family_id=family_id, parent_token_id=parent_id,
                )
                db.add(record)
                await db.flush()
                chain.append({"id": record.id, "raw": raw, "hash": token_hash})
                parent_id = record.id

            for i in range(length - 1):
                prev = await db.get(RefreshToken, chain[i]["id"])
                prev.revoked = True
                prev.replaced_by_token_id = chain[i + 1]["id"]
            await db.commit()
        finally:
            await db.close()
        return family_id, chain

    async def _create_standalone_logged_out_token(self) -> dict:
        """A single revoked token with NO replaced_by_token_id — simulates a
        plain logout, not a rotation."""
        family_id = str(uuid4())
        db = self.session_factory()
        try:
            db.add(RefreshTokenFamily(token_family_id=family_id))
            await db.flush()
            raw = create_refresh_token()
            token_hash = hash_refresh_token(raw)
            record = RefreshToken(
                user_id=self.user_id, token_hash=token_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                revoked=True, mfa_satisfied=False,
                last_used_at=datetime.now(timezone.utc),
                token_family_id=family_id, parent_token_id=None,
            )
            db.add(record)
            await db.commit()
            return {"id": record.id, "raw": raw, "hash": token_hash, "family_id": family_id}
        finally:
            await db.close()

    async def _refresh(self, client: httpx.AsyncClient, raw_token: str) -> httpx.Response:
        return await client.post("/api/auth/refresh", json={"refresh_token": raw_token})

    async def _family_tokens(self, family_id: str) -> list[RefreshToken]:
        db = self.session_factory()
        try:
            rows = (await db.scalars(
                select(RefreshToken).where(RefreshToken.token_family_id == family_id).order_by(RefreshToken.id.asc())
            )).all()
            return list(rows)
        finally:
            await db.close()

    async def _audit_actions_for_session(self, session_id: int) -> list[str]:
        db = self.session_factory()
        try:
            rows = (await db.scalars(
                select(AdminAuditLog.action).where(AdminAuditLog.session_id == str(session_id))
            )).all()
            return list(rows)
        finally:
            await db.close()

    async def test_concurrent_replay_of_same_valid_token_exactly_one_succeeds(self):
        family_id, chain = await self._create_chain(1)
        raw_token = chain[0]["raw"]

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            responses = await asyncio.gather(
                self._refresh(client, raw_token), self._refresh(client, raw_token),
            )

        statuses = sorted(r.status_code for r in responses)
        self.assertEqual(statuses, [200, 401])

        family_tokens = await self._family_tokens(family_id)
        # Every token in the family — including the winner's newly-issued
        # child — must end up revoked once replay detection fires.
        self.assertTrue(all(t.revoked for t in family_tokens))
        self.assertGreaterEqual(len(family_tokens), 2)  # original + at least the winner's new child

        audit_actions = await self._audit_actions_for_session(chain[0]["id"])
        self.assertIn("refresh.reuse_detected", audit_actions)

    async def test_sequential_reuse_of_already_rotated_token_revokes_family(self):
        family_id, chain = await self._create_chain(2)  # root (already rotated) -> current
        root, current = chain

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await self._refresh(client, root["raw"])

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Session invalidated. Please log in again.")

        family_tokens = await self._family_tokens(family_id)
        self.assertTrue(all(t.revoked for t in family_tokens))  # the still-valid "current" got swept up too

        audit_actions = await self._audit_actions_for_session(root["id"])
        self.assertIn("refresh.reuse_detected", audit_actions)

    async def test_reuse_of_logged_out_token_does_not_trigger_family_revocation(self):
        token = await self._create_standalone_logged_out_token()

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await self._refresh(client, token["raw"])

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Session invalidated. Please log in again.")

        audit_actions = await self._audit_actions_for_session(token["id"])
        self.assertIn("refresh.revoked_token_reuse", audit_actions)
        self.assertNotIn("refresh.reuse_detected", audit_actions)

    async def test_normal_rotation_chain_keeps_one_family_with_correct_lineage(self):
        family_id, chain = await self._create_chain(1)
        raw_token = chain[0]["raw"]
        root_id = chain[0]["id"]

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        seen_ids = [root_id]
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            for _ in range(3):
                response = await self._refresh(client, raw_token)
                self.assertEqual(response.status_code, 200)
                raw_token = response.json()["refresh_token"]

        family_tokens = await self._family_tokens(family_id)
        self.assertEqual(len(family_tokens), 4)  # root + 3 rotations
        self.assertTrue(all(t.token_family_id == family_id for t in family_tokens))

        by_id = {t.id: t for t in family_tokens}
        current = next(t for t in family_tokens if not t.revoked)
        chain_walked = [current.id]
        cursor = current
        while cursor.parent_token_id is not None:
            cursor = by_id[cursor.parent_token_id]
            chain_walked.append(cursor.id)
        self.assertEqual(chain_walked[-1], root_id)
        self.assertEqual(len(chain_walked), 4)
        # Every revoked ancestor points forward to its actual successor.
        for i in range(len(chain_walked) - 1):
            child_id, parent_id = chain_walked[i], chain_walked[i + 1]
            self.assertEqual(by_id[parent_id].replaced_by_token_id, child_id)

    async def test_ancestor_replay_racing_with_descendant_rotation_leaves_no_valid_token(self):
        # root(A, revoked) -> child(B, revoked) -> child(C, current valid)
        family_id, chain = await self._create_chain(3)
        root, child_b, current_c = chain

        from app.models.refresh_token_family import RefreshTokenFamily as _RTF
        lock_calls: list[str] = []

        async def _spy_lock_token_family(db, *, token_family_id):
            lock_calls.append(token_family_id)
            await db.execute(
                select(_RTF.token_family_id)
                .where(_RTF.token_family_id == token_family_id)
                .with_for_update()
            )

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        with patch("app.api.routes.auth.lock_token_family", new=_spy_lock_token_family), \
             patch("app.services.refresh_token_replay.lock_token_family", new=_spy_lock_token_family):
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
                try:
                    replay_response, rotation_response = await asyncio.wait_for(
                        asyncio.gather(
                            self._refresh(client, root["raw"]),       # ancestor replay
                            self._refresh(client, current_c["raw"]),  # legitimate descendant rotation
                        ),
                        timeout=10.0,
                    )
                except asyncio.TimeoutError:
                    self.fail("ancestor-replay vs descendant-rotation race deadlocked (exceeded 10s timeout)")

        # The replay must always be rejected — it presents an already-revoked
        # ancestor token no matter which side wins the family lock.
        self.assertEqual(replay_response.status_code, 401)

        # No unrevoked token may remain anywhere in the family afterward,
        # regardless of scheduling order — including any child the rotation
        # attempt may have briefly created before the replay's revocation
        # swept it up.
        family_tokens = await self._family_tokens(family_id)
        self.assertTrue(
            all(t.revoked for t in family_tokens),
            f"found an unrevoked token after the race: {[(t.id, t.revoked) for t in family_tokens]}",
        )

        # Both code paths — ordinary rotation (auth.py's own call) and
        # revoke_token_family's internal call — actually went through the
        # shared lock, not merely inferred from the end state.
        self.assertGreaterEqual(len(lock_calls), 2)
        self.assertTrue(all(fid == family_id for fid in lock_calls))

        if rotation_response.status_code == 200:
            # Rotation won the lock first, briefly creating a new child —
            # that child must have been swept up by the replay's subsequent
            # family-wide revocation.
            new_token_hash = hash_refresh_token(rotation_response.json()["refresh_token"])
            db = self.session_factory()
            try:
                new_record = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == new_token_hash))
            finally:
                await db.close()
            self.assertIsNotNone(new_record)
            self.assertTrue(new_record.revoked)
        else:
            self.assertEqual(rotation_response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
