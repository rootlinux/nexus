import asyncio
import os
import secrets
import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xplatform")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.api.deps import get_db
from app.main import app
from app.models.invite import InviteCode, InviteType
from app.models.invite_campaign import InviteCampaign
from app.models.invite_usage import InviteUsage
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserStatus
from app.services.invite_campaigns import CampaignRuleViolation, create_campaign_invite, get_campaign_counts


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_BIN = BACKEND_ROOT / ".venv" / "bin" / "alembic"


class Phase3WaveCampaignConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.prefix = f"phase3c_{uuid4().hex[:8]}"
        self.db_name = f"{self.prefix}_db"
        self.database_url = f"postgresql+asyncpg://postgres:postgres@localhost:5432/{self.db_name}"
        self._provision_database()
        self.engine = create_async_engine(
            self.database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=1800,
            connect_args={"statement_cache_size": 0},
        )
        self.SessionLocal = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
        )
        app.dependency_overrides.clear()

        async def override_db():
            async with self.SessionLocal() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db] = override_db

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.engine.dispose()
        self._drop_database()

    def _provision_database(self) -> None:
        self._run_command(["dropdb", "--if-exists", self.db_name])
        self._run_command(["createdb", self.db_name])
        env = dict(os.environ)
        env["DATABASE_URL"] = self.database_url
        env.setdefault("REDIS_URL", "redis://localhost:6379/0")
        env.setdefault("SECRET_KEY", secrets.token_hex(32))
        result = subprocess.run(
            [str(ALEMBIC_BIN), "upgrade", "head"],
            cwd=BACKEND_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.fail(
                "failed to provision concurrency test database\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )

    def _drop_database(self) -> None:
        self._run_command(["dropdb", "--if-exists", "--force", self.db_name])

    def _run_command(self, command: list[str]) -> None:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            self.fail(
                f"command failed: {' '.join(command)}\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )

    async def _create_user(self, suffix: str) -> User:
        user = User(
            username=f"{self.prefix}_{suffix}",
            email=f"{self.prefix}_{suffix}@example.com",
            password_hash="test-password-hash",
            display_name=suffix,
            is_active=True,
            status=UserStatus.ACTIVE,
        )
        async with self.SessionLocal() as db:
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return user

    async def _create_campaign(
        self,
        *,
        slug_suffix: str,
        created_by_user_id: int,
        max_uses_total: int | None,
        per_user_invite_allowance: int,
    ) -> InviteCampaign:
        campaign = InviteCampaign(
            name=f"{self.prefix} {slug_suffix}",
            slug=f"{self.prefix}-{slug_suffix}",
            is_active=True,
            active_from=datetime.utcnow() - timedelta(minutes=5),
            expires_at=datetime.utcnow() + timedelta(hours=1),
            max_uses_total=max_uses_total,
            per_user_invite_allowance=per_user_invite_allowance,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=created_by_user_id,
        )
        async with self.SessionLocal() as db:
            db.add(campaign)
            await db.commit()
            await db.refresh(campaign)
        return campaign

    async def _create_campaign_invite_row(
        self,
        *,
        campaign_id: int,
        creator: User,
        assigned_to_user: User | None = None,
    ) -> InviteCode:
        invite = InviteCode(
            code=f"P3C{uuid4().hex[:24]}",
            invite_type=InviteType.REFERRAL,
            created_by_id=creator.id,
            generated_by_user_id=assigned_to_user.id if assigned_to_user else None,
            assigned_to_user_id=assigned_to_user.id if assigned_to_user else None,
            assigned_to_username=assigned_to_user.username if assigned_to_user else None,
            campaign_id=campaign_id,
            max_uses=1,
            current_uses=0,
            is_active=True,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        async with self.SessionLocal() as db:
            db.add(invite)
            await db.commit()
            await db.refresh(invite)
        return invite

    async def test_concurrent_generation_enforces_total_cap_in_db(self):
        creator = await self._create_user("creator_total")
        actor_one = await self._create_user("generator_a")
        actor_two = await self._create_user("generator_b")
        campaign = await self._create_campaign(
            slug_suffix="total-cap",
            created_by_user_id=creator.id,
            max_uses_total=1,
            per_user_invite_allowance=2,
        )

        async def attempt(actor_id: int, code_suffix: str, hold_lock: bool = False):
            async with self.SessionLocal() as db:
                async with db.begin():
                    campaign_row = (
                        await db.execute(
                            select(InviteCampaign)
                            .where(InviteCampaign.id == campaign.id)
                            .with_for_update()
                        )
                    ).scalar_one()
                    actor = (
                        await db.execute(
                            select(User)
                            .options(selectinload(User.staff_permission))
                            .where(User.id == actor_id)
                        )
                    ).scalar_one()
                    if hold_lock:
                        await asyncio.sleep(0.2)
                    try:
                        invite, _ = await create_campaign_invite(
                            db,
                            campaign=campaign_row,
                            actor=actor,
                            code=f"{self.prefix.upper()}T{code_suffix}",
                        )
                        return ("created", invite.code)
                    except CampaignRuleViolation as exc:
                        return ("blocked", exc.code)

        first = asyncio.create_task(attempt(actor_one.id, "A", hold_lock=True))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(attempt(actor_two.id, "B"))
        outcomes = await asyncio.wait_for(asyncio.gather(first, second), timeout=5)

        self.assertEqual(sorted(status for status, _ in outcomes), ["blocked", "created"])
        self.assertIn(("blocked", "generation_limit_reached"), outcomes)

        async with self.SessionLocal() as db:
            counts = await get_campaign_counts(db, campaign.id)
            generated_by_users = (
                await db.execute(
                    select(InviteCode.generated_by_user_id).where(InviteCode.campaign_id == campaign.id)
                )
            ).scalars().all()

        self.assertEqual(counts, {"generated_count": 1, "consumed_count": 0})
        self.assertEqual(len(generated_by_users), 1)

    async def test_concurrent_generation_does_not_bypass_per_user_allowance(self):
        creator = await self._create_user("creator_allowance")
        actor = await self._create_user("generator_same_user")
        campaign = await self._create_campaign(
            slug_suffix="allowance-cap",
            created_by_user_id=creator.id,
            max_uses_total=5,
            per_user_invite_allowance=1,
        )

        async def attempt(code_suffix: str, hold_lock: bool = False):
            async with self.SessionLocal() as db:
                async with db.begin():
                    campaign_row = (
                        await db.execute(
                            select(InviteCampaign)
                            .where(InviteCampaign.id == campaign.id)
                            .with_for_update()
                        )
                    ).scalar_one()
                    actor_row = (
                        await db.execute(
                            select(User)
                            .options(selectinload(User.staff_permission))
                            .where(User.id == actor.id)
                        )
                    ).scalar_one()
                    if hold_lock:
                        await asyncio.sleep(0.2)
                    try:
                        invite, _ = await create_campaign_invite(
                            db,
                            campaign=campaign_row,
                            actor=actor_row,
                            code=f"{self.prefix.upper()}A{code_suffix}",
                        )
                        return ("created", invite.code)
                    except CampaignRuleViolation as exc:
                        return ("blocked", exc.code)

        first = asyncio.create_task(attempt("1", hold_lock=True))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(attempt("2"))
        outcomes = await asyncio.wait_for(asyncio.gather(first, second), timeout=5)

        self.assertEqual(sorted(status for status, _ in outcomes), ["blocked", "created"])
        self.assertIn(("blocked", "allowance_exhausted"), outcomes)

        async with self.SessionLocal() as db:
            counts = await get_campaign_counts(db, campaign.id)
            user_generated_count = (
                await db.execute(
                    select(func.count(InviteCode.id)).where(
                        InviteCode.campaign_id == campaign.id,
                        InviteCode.generated_by_user_id == actor.id,
                    )
                )
            ).scalar_one()

        self.assertEqual(counts, {"generated_count": 1, "consumed_count": 0})
        self.assertEqual(int(user_generated_count), 1)

    async def test_concurrent_redemption_does_not_double_consume_invite(self):
        creator = await self._create_user("creator_redeem")
        campaign = await self._create_campaign(
            slug_suffix="redeem-cap",
            created_by_user_id=creator.id,
            max_uses_total=1,
            per_user_invite_allowance=2,
        )
        invite = await self._create_campaign_invite_row(campaign_id=campaign.id, creator=creator)
        redeem_usernames = [f"r{uuid4().hex[:8]}", f"r{uuid4().hex[:7]}x"]

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        with patch("app.api.routes.auth.enforce_rate_limits", new=AsyncMock()):
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
                async def register(username: str):
                    return await client.post(
                        "/api/auth/register",
                        json={
                            "username": username,
                            "display_name": username,
                            "email": f"{username}@example.com",
                            "password": "Phase3Password123!",
                            "invite_code": invite.code,
                        },
                    )

                first = asyncio.create_task(register(redeem_usernames[0]))
                second = asyncio.create_task(register(redeem_usernames[1]))
                responses = await asyncio.wait_for(asyncio.gather(first, second), timeout=10)

        status_codes = sorted(response.status_code for response in responses)
        self.assertEqual(status_codes, [201, 400])

        async with self.SessionLocal() as db:
            invite_row = (
                await db.execute(select(InviteCode).where(InviteCode.id == invite.id))
            ).scalar_one()
            usage_count = (
                await db.execute(
                    select(func.count(InviteUsage.id)).where(InviteUsage.invite_id == invite.id)
                )
            ).scalar_one()
            created_users = (
                await db.execute(
                    select(User.username).where(
                        User.username.in_(redeem_usernames)
                    )
                )
            ).scalars().all()
            counts = await get_campaign_counts(db, campaign.id)

        self.assertEqual(invite_row.current_uses, 1)
        self.assertFalse(invite_row.is_active)
        self.assertIsNotNone(invite_row.used_by_user_id)
        self.assertEqual(int(usage_count), 1)
        self.assertEqual(len(created_users), 1)
        self.assertEqual(counts, {"generated_count": 1, "consumed_count": 1})


if __name__ == "__main__":
    unittest.main()
