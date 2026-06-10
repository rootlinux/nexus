import os
import subprocess
import sys
import textwrap
import unittest


class ReleaseBlockerRegressionTests(unittest.TestCase):
    def test_release_blockers_runtime_paths(self):
        env = dict(os.environ)
        env["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/xplatform"
        env.setdefault("REDIS_URL", "redis://localhost:6379/0")
        env.setdefault("SECRET_KEY", "release-blocker-test-secret")
        env["DEBUG"] = "false"

        script = textwrap.dedent(
            """
            import asyncio
            from datetime import datetime, timedelta, timezone
            from uuid import uuid4

            import httpx
            import jwt
            from sqlalchemy import delete, func, or_, select

            from app.core.config import settings
            from app.core.database import AsyncSessionLocal
            from app.main import app
            from app.models.block import Block
            from app.models.dm import DirectMessage
            from app.models.moderation_signal import ModerationSignal
            from app.models.user import User, UserStatus


            async def main():
                created_user_ids = []

                async def create_user(prefix, invited_by_user_id=None):
                    suffix = uuid4().hex[:12]
                    user = User(
                        username=f"{prefix}_{suffix}",
                        email=f"{prefix}_{suffix}@example.com",
                        password_hash="test-password-hash",
                        display_name=prefix,
                        is_active=True,
                        email_verified_at=datetime.utcnow(),
                        status=UserStatus.ACTIVE,
                        invited_by_user_id=invited_by_user_id,
                    )
                    async with AsyncSessionLocal() as db:
                        db.add(user)
                        await db.commit()
                        await db.refresh(user)
                    created_user_ids.append(user.id)
                    return user

                def token_for(user):
                    return jwt.encode(
                        {
                            "sub": str(user.id),
                            "username": user.username,
                            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
                        },
                        settings.SECRET_KEY,
                        algorithm=settings.ALGORITHM,
                    )

                async def count_dms(sender_id, receiver_id):
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(
                            select(func.count(DirectMessage.id)).where(
                                DirectMessage.sender_id == sender_id,
                                DirectMessage.receiver_id == receiver_id,
                            )
                        )
                        return int(result.scalar() or 0)

                async def cleanup():
                    if not created_user_ids:
                        return

                    async with AsyncSessionLocal() as db:
                        dm_ids = (
                            await db.execute(
                                select(DirectMessage.id).where(
                                    or_(
                                        DirectMessage.sender_id.in_(created_user_ids),
                                        DirectMessage.receiver_id.in_(created_user_ids),
                                    )
                                )
                            )
                        ).scalars().all()
                        if dm_ids:
                            await db.execute(delete(ModerationSignal).where(ModerationSignal.dm_message_id.in_(dm_ids)))
                        await db.execute(
                            delete(ModerationSignal).where(
                                or_(
                                    ModerationSignal.user_id.in_(created_user_ids),
                                    ModerationSignal.resolved_by_user_id.in_(created_user_ids),
                                )
                            )
                        )
                        await db.execute(
                            delete(DirectMessage).where(
                                or_(
                                    DirectMessage.sender_id.in_(created_user_ids),
                                    DirectMessage.receiver_id.in_(created_user_ids),
                                )
                            )
                        )
                        await db.execute(
                            delete(Block).where(
                                or_(
                                    Block.blocker_id.in_(created_user_ids),
                                    Block.blocked_id.in_(created_user_ids),
                                )
                            )
                        )
                        await db.execute(delete(User).where(User.id.in_(created_user_ids)))
                        await db.commit()

                transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
                async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
                    try:
                        inviter = await create_user("search_inviter")
                        viewer = await create_user("search_viewer")
                        matched = await create_user("apisweep_match", invited_by_user_id=inviter.id)

                        search_response = await client.get(
                            "/api/search",
                            params={"q": "apisweep_match", "type": "top"},
                            headers={"Authorization": f"Bearer {token_for(viewer)}"},
                        )
                        assert search_response.status_code == 200, search_response.text
                        search_payload = search_response.json()
                        matched_payload = next(user for user in search_payload["users"] if user["username"] == matched.username)
                        assert matched_payload["inviter"]["username"] == inviter.username, matched_payload

                        empty_response = await client.get(
                            "/api/search",
                            params={"q": "zzznomatchrelease", "type": "top"},
                            headers={"Authorization": f"Bearer {token_for(viewer)}"},
                        )
                        assert empty_response.status_code == 200, empty_response.text
                        empty_payload = empty_response.json()
                        assert empty_payload["users"] == [], empty_payload
                        assert empty_payload["posts"] == [], empty_payload

                        blocker = await create_user("blocker")
                        blocked = await create_user("blocked")

                        block_response = await client.post(
                            f"/api/users/{blocked.username}/block",
                            headers={"Authorization": f"Bearer {token_for(blocker)}"},
                        )
                        assert block_response.status_code == 200, block_response.text
                        assert block_response.json() == {"is_blocked": True}, block_response.text

                        profile_response = await client.get(
                            f"/api/users/{blocker.username}",
                            headers={"Authorization": f"Bearer {token_for(blocked)}"},
                        )
                        assert profile_response.status_code == 404, profile_response.text

                        dm_count_before = await count_dms(blocked.id, blocker.id)
                        send_response = await client.post(
                            f"/api/dm/conversations/{blocker.username}",
                            headers={"Authorization": f"Bearer {token_for(blocked)}"},
                            json={"content": "blocked message attempt"},
                        )
                        assert send_response.status_code == 403, send_response.text
                        assert await count_dms(blocked.id, blocker.id) == dm_count_before

                        messages_response = await client.get(
                            f"/api/dm/conversations/{blocker.username}/messages",
                            headers={"Authorization": f"Bearer {token_for(blocked)}"},
                        )
                        assert messages_response.status_code == 404, messages_response.text

                        unblock_response = await client.post(
                            f"/api/users/{blocked.username}/block",
                            headers={"Authorization": f"Bearer {token_for(blocker)}"},
                        )
                        assert unblock_response.status_code == 200, unblock_response.text
                        assert unblock_response.json() == {"is_blocked": False}, unblock_response.text

                        restored_profile = await client.get(
                            f"/api/users/{blocker.username}",
                            headers={"Authorization": f"Bearer {token_for(blocked)}"},
                        )
                        assert restored_profile.status_code == 200, restored_profile.text

                        restored_send = await client.post(
                            f"/api/dm/conversations/{blocker.username}",
                            headers={"Authorization": f"Bearer {token_for(blocked)}"},
                            json={"content": "message after unblock"},
                        )
                        assert restored_send.status_code == 200, restored_send.text
                        assert await count_dms(blocked.id, blocker.id) == dm_count_before + 1
                    finally:
                        await cleanup()

            asyncio.run(main())
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.fail(f"runtime regression check failed\\nSTDOUT:\\n{result.stdout}\\nSTDERR:\\n{result.stderr}")


if __name__ == "__main__":
    unittest.main()
