import os
import subprocess
import sys
import textwrap
import unittest


class PushNotificationIntegrationTests(unittest.TestCase):
    def test_push_notification_end_to_end_behaviors(self):
        env = dict(os.environ)
        env["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/xplatform"
        env.setdefault("REDIS_URL", "redis://localhost:6379/0")
        env.setdefault("SECRET_KEY", "push-notification-test-secret")
        env["DEBUG"] = "false"
        env.setdefault("VAPID_PUBLIC_KEY", "test-public-key")
        env.setdefault("VAPID_PRIVATE_KEY", "test-private-key")
        env.setdefault("VAPID_SUBJECT", "mailto:test@example.com")

        script = textwrap.dedent(
            """
            import asyncio
            from datetime import datetime, timedelta, timezone
            from uuid import uuid4

            import httpx
            import jwt
            from sqlalchemy import delete, select

            from app.core.config import settings
            from app.core.database import AsyncSessionLocal
            from app.main import app
            from app.models.notification import NotificationType
            from app.models.notification_settings import NotificationSettings
            from app.models.user import User, UserStatus
            from app.services.notifications import create_follow_notification
            from app.services.push_notifications import PushDeliveryError


            async def main():
                created_user_ids = []
                touched_endpoints = []

                async def create_user(prefix):
                    suffix = uuid4().hex[:12]
                    user = User(
                        username=f"{prefix}_{suffix}",
                        email=f"{prefix}_{suffix}@example.com",
                        password_hash="test-password-hash",
                        display_name=prefix,
                        is_active=True,
                        email_verified_at=datetime.utcnow(),
                        status=UserStatus.ACTIVE,
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

                async def cleanup():
                    async with AsyncSessionLocal() as db:
                        push_model = __import__("app.models.push_subscription", fromlist=["PushSubscription"]).PushSubscription
                        if touched_endpoints:
                            await db.execute(delete(push_model).where(push_model.endpoint.in_(touched_endpoints)))
                        if created_user_ids:
                            await db.execute(delete(NotificationSettings).where(NotificationSettings.user_id.in_(created_user_ids)))
                            await db.execute(delete(User).where(User.id.in_(created_user_ids)))
                        await db.commit()

                transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
                async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
                    try:
                        recipient = await create_user("push_recipient")
                        actor = await create_user("push_actor")
                        auth_headers = {"Authorization": f"Bearer {token_for(recipient)}"}

                        endpoint_a = f"https://push.example.test/{uuid4().hex}/a"
                        endpoint_b = f"https://push.example.test/{uuid4().hex}/b"
                        touched_endpoints.extend([endpoint_a, endpoint_b])

                        put_a = await client.put(
                            "/api/notifications/push-subscriptions",
                            headers=auth_headers,
                            json={
                                "endpoint": endpoint_a,
                                "keys": {"p256dh": "p256dh-a-1", "auth": "auth-a-1"},
                                "user_agent": "Browser A",
                            },
                        )
                        assert put_a.status_code == 200, put_a.text

                        put_a_again = await client.put(
                            "/api/notifications/push-subscriptions",
                            headers=auth_headers,
                            json={
                                "endpoint": endpoint_a,
                                "keys": {"p256dh": "p256dh-a-2", "auth": "auth-a-2"},
                                "user_agent": "Browser A Updated",
                            },
                        )
                        assert put_a_again.status_code == 200, put_a_again.text
                        assert put_a_again.json()["subscription"]["p256dh"] == "p256dh-a-2", put_a_again.text

                        put_b = await client.put(
                            "/api/notifications/push-subscriptions",
                            headers=auth_headers,
                            json={
                                "endpoint": endpoint_b,
                                "keys": {"p256dh": "p256dh-b", "auth": "auth-b"},
                                "user_agent": "Browser B",
                            },
                        )
                        assert put_b.status_code == 200, put_b.text

                        listed = await client.get("/api/notifications/push-subscriptions", headers=auth_headers)
                        assert listed.status_code == 200, listed.text
                        listed_payload = listed.json()
                        assert len(listed_payload["subscriptions"]) == 2, listed_payload
                        assert {item["endpoint"] for item in listed_payload["subscriptions"]} == {endpoint_a, endpoint_b}, listed_payload

                        from app.services import push_notifications

                        deliveries = []
                        failing_endpoint = endpoint_b

                        async def fake_send(subscription, payload):
                            deliveries.append((subscription.endpoint, payload["notification_type"]))
                            if subscription.endpoint == failing_endpoint:
                                raise PushDeliveryError("expired subscription", status_code=410)

                        push_notifications.send_web_push_message = fake_send

                        async with AsyncSessionLocal() as db:
                            await create_follow_notification(
                                db,
                                actor_user_id=actor.id,
                                target_user_id=recipient.id,
                            )
                            await db.commit()

                        assert deliveries == [
                            (endpoint_a, NotificationType.FOLLOW.value),
                            (endpoint_b, NotificationType.FOLLOW.value),
                        ], deliveries

                        listed_after_failure = await client.get("/api/notifications/push-subscriptions", headers=auth_headers)
                        assert listed_after_failure.status_code == 200, listed_after_failure.text
                        status_by_endpoint = {
                            item["endpoint"]: item["is_active"]
                            for item in listed_after_failure.json()["subscriptions"]
                        }
                        assert status_by_endpoint[endpoint_a] is True, status_by_endpoint
                        assert status_by_endpoint[endpoint_b] is False, status_by_endpoint

                        deliveries.clear()
                        failing_endpoint = None
                        async with AsyncSessionLocal() as db:
                            settings_row = (
                                await db.execute(
                                    select(NotificationSettings).where(NotificationSettings.user_id == recipient.id)
                                )
                            ).scalar_one()
                            settings_row.push_follows = False
                            await db.commit()

                        async with AsyncSessionLocal() as db:
                            await create_follow_notification(
                                db,
                                actor_user_id=actor.id,
                                target_user_id=recipient.id,
                            )
                            await db.commit()

                        assert deliveries == [], deliveries

                        test_send = await client.post(
                            "/api/notifications/push-subscriptions/test-send",
                            headers=auth_headers,
                            json={"title": "Test push", "body": "Smoke", "url": "/notifications"},
                        )
                        assert test_send.status_code == 200, test_send.text
                        test_send_payload = test_send.json()
                        assert test_send_payload["sent_count"] == 1, test_send_payload
                        assert test_send_payload["failed_count"] == 0, test_send_payload

                        delete_b = await client.request(
                            "DELETE",
                            "/api/notifications/push-subscriptions",
                            headers=auth_headers,
                            json={"endpoint": endpoint_b},
                        )
                        assert delete_b.status_code == 200, delete_b.text

                        listed_after_delete = await client.get("/api/notifications/push-subscriptions", headers=auth_headers)
                        assert listed_after_delete.status_code == 200, listed_after_delete.text
                        remaining = listed_after_delete.json()["subscriptions"]
                        assert len(remaining) == 1, remaining
                        assert remaining[0]["endpoint"] == endpoint_a, remaining
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
            self.fail(f"push notification regression failed\\nSTDOUT:\\n{result.stdout}\\nSTDERR:\\n{result.stderr}")


if __name__ == "__main__":
    unittest.main()
