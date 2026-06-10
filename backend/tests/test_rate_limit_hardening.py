import asyncio
import os
import secrets
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from redis.exceptions import RedisError

from app.api import deps
from app.api.dm import _dm_send_policies
from app.api.routes import admin, auth, posts
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import RATE_LIMIT_BACKEND_ERROR, RateLimitPolicy, _memory_rate_limiter, hit_rate_limit
from app.main import app
from app.models.like import Like
from app.models.post import Post


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDBSession:
    def __init__(self, *, post_id: int = 1, post_owner_id: int = 200, likes_count: int = 0):
        self.post = Post(id=post_id, user_id=post_owner_id, content="hello", likes_count=likes_count)
        self._liked = False

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is Post:
            return _ScalarResult(self.post)
        if entity is Like:
            if not self._liked:
                return _ScalarResult(None)
            return _ScalarResult(Like(user_id=100, post_id=self.post.id))
        raise AssertionError(f"Unexpected statement entity: {entity}")

    def add(self, instance):
        if isinstance(instance, Like):
            self._liked = True

    async def delete(self, instance):
        self._liked = False

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def refresh(self, instance):
        return None


class RateLimitHardeningTests(unittest.TestCase):
    def setUp(self):
        self._original_env = settings.APP_ENV
        _memory_rate_limiter._fixed_counters.clear()
        _memory_rate_limiter._sliding_counters.clear()
        app.dependency_overrides.clear()

    def tearDown(self):
        settings.APP_ENV = self._original_env
        _memory_rate_limiter._fixed_counters.clear()
        _memory_rate_limiter._sliding_counters.clear()
        app.dependency_overrides.clear()

    def _build_client(self, db: _FakeDBSession) -> TestClient:
        async def override_db():
            yield db

        async def override_user():
            return SimpleNamespace(id=100, username="liker", status=None, is_active=True)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[deps.get_current_interactive_user] = override_user
        return TestClient(app, base_url="http://localhost")

    def test_like_toggle_allows_normal_usage(self):
        db = _FakeDBSession()
        with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
            with patch("app.api.routes.posts.create_like_notification", new=AsyncMock()) as notify_mock:
                with patch(
                    "app.api.routes.posts.get_block_relationship",
                    new=AsyncMock(return_value=SimpleNamespace(is_blocked=False)),
                ):
                    client = self._build_client(db)
                    first = client.post("/api/posts/1/like")
                    second = client.post("/api/posts/1/like")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), {"liked": True, "likes_count": 1})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), {"liked": False, "likes_count": 0})
        notify_mock.assert_awaited_once()

    def test_like_toggle_hits_real_backend_limit_under_rapid_hammering(self):
        db = _FakeDBSession()
        with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
            with patch("app.api.routes.posts.create_like_notification", new=AsyncMock()):
                with patch(
                    "app.api.routes.posts.get_block_relationship",
                    new=AsyncMock(return_value=SimpleNamespace(is_blocked=False)),
                ):
                    client = self._build_client(db)
                    statuses = [client.post("/api/posts/1/like").status_code for _ in range(4)]
                    blocked = client.post("/api/posts/1/like")

        self.assertEqual(statuses[:4], [200, 200, 200, 200])
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["detail"], "You're doing that too often. Please wait and try again.")
        self.assertEqual(blocked.headers["x-ratelimit-policy"], "like-toggle-post-hammer")

    def test_critical_like_route_fails_closed_when_redis_is_required_in_production(self):
        settings.APP_ENV = "production"
        db = _FakeDBSession()
        with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
            with patch(
                "app.api.routes.posts.get_block_relationship",
                new=AsyncMock(return_value=SimpleNamespace(is_blocked=False)),
            ):
                client = self._build_client(db)
                response = client.post("/api/posts/1/like")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], RATE_LIMIT_BACKEND_ERROR)
        self.assertEqual(response.headers["retry-after"], "30")

    def test_high_risk_route_groups_use_sliding_window(self):
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))

        login_policies = auth._login_limit_policies(request, "demo")
        register_policies = auth._register_limit_policies(request, "invite-code")
        refresh_policies = auth._refresh_limit_policies(request, "refresh-token")
        dm_policies = _dm_send_policies(1, "target")
        post_policies = posts._post_mutation_policies(1)
        reply_policies = posts._reply_mutation_policies(1)
        strict_admin_policies = admin._admin_mutation_policies(1, "user-ban", strict=True)

        for group in (
            login_policies,
            register_policies,
            refresh_policies,
            dm_policies,
            post_policies,
            reply_policies,
            strict_admin_policies,
        ):
            self.assertTrue(all(policy.strategy == "sliding_window" for policy in group))
            self.assertTrue(all(policy.require_redis_in_production for policy in group))

        self.assertTrue(all(policy.strategy == "sliding_window" for policy in posts._like_toggle_policies(1)))
        self.assertTrue(all(policy.strategy == "sliding_window" for policy in posts._like_toggle_target_policies(1, 2, 3)))

    def test_lower_risk_routes_remain_memory_fallback_eligible(self):
        self.assertFalse(posts._repost_mutation_policies(1)[0].require_redis_in_production)
        self.assertFalse(posts._bookmark_mutation_policies(1)[0].require_redis_in_production)
        self.assertFalse(admin._admin_mutation_policies(1, "invite-reveal", strict=False)[0].require_redis_in_production)

    def test_lower_risk_policy_uses_memory_fallback_during_redis_outage(self):
        settings.APP_ENV = "production"
        policy = RateLimitPolicy(
            name="bookmark-toggle",
            limit=40,
            window_seconds=600,
            key="bookmark:toggle:test-user",
        )

        with patch("app.core.rate_limit._hit_redis_limit", new=AsyncMock(side_effect=RedisError("down"))):
            result = asyncio.run(hit_rate_limit(policy))

        self.assertTrue(result.allowed)
        self.assertEqual(result.backend, "memory")


if __name__ == "__main__":
    unittest.main()
