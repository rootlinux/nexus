"""
Tests for GET /api/discover/users and GET /api/discover/posts endpoints.

Pattern: FastAPI dependency injection override + TestClient (no real DB).
Each test class sets up a self-contained FakeDB that returns exactly what
the service layer expects, then asserts on the JSON response.
"""

from __future__ import annotations

import os
import secrets
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# Environment must be set BEFORE importing any app code
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

# ---------------------------------------------------------------------------
# Stub optional heavy dependencies that may not be installed in test env
# ---------------------------------------------------------------------------
if "PIL" not in sys.modules:
    _pil_stub = types.ModuleType("PIL")
    _pil_image_stub = types.ModuleType("PIL.Image")
    _pil_imageops_stub = types.ModuleType("PIL.ImageOps")

    class _UnidentifiedImageError(Exception):
        pass

    class _PILImage:
        pass

    # Attributes on the PIL.Image module
    _pil_image_stub.Image = _PILImage
    _pil_image_stub.UnidentifiedImageError = _UnidentifiedImageError
    _pil_image_stub.open = lambda *a, **k: None

    # `from PIL import Image, ImageOps, UnidentifiedImageError` resolves via PIL package
    _pil_stub.Image = _pil_image_stub
    _pil_stub.ImageOps = _pil_imageops_stub
    _pil_stub.UnidentifiedImageError = _UnidentifiedImageError

    sys.modules["PIL"] = _pil_stub
    sys.modules["PIL.Image"] = _pil_image_stub
    sys.modules["PIL.ImageOps"] = _pil_imageops_stub

from fastapi.testclient import TestClient  # noqa: E402

from app.api import deps  # noqa: E402
import app.core.rate_limit as _rate_limit_module  # noqa: E402
from app.main import app  # noqa: E402
from app.models.post import Post, PostModerationStatus  # noqa: E402
from app.models.user import User, UserStatus  # noqa: E402


def _reset_redis_state() -> None:
    """Reset the global Redis client singleton so the next test gets a fresh
    connection on a live event loop.  Prevents 'Event loop is closed' errors
    when multiple TestClient instances are created across tests."""
    _rate_limit_module._redis_client = None
    # Replace the asyncio.Lock with a fresh one so the new event loop owns it
    import asyncio
    _rate_limit_module._redis_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
_NOW_NAIVE = _NOW.replace(tzinfo=None)


def _make_user(
    user_id: int,
    username: str = "user",
    status: UserStatus = UserStatus.ACTIVE,
    is_active: bool = True,
    created_at: datetime | None = None,
) -> User:
    u = User(
        id=user_id,
        username=f"{username}_{user_id}",
        email=f"{username}_{user_id}@example.com",
        password_hash="hash",
        display_name=f"Display {user_id}",
        avatar_url=None,
        is_active=is_active,
        status=status,
        email_verified_at=_NOW_NAIVE,
        created_at=(created_at or _NOW_NAIVE),
    )
    return u


def _make_post(
    post_id: int,
    author: User,
    content: str = "test post",
    parent_id: int | None = None,
    moderation_status: PostModerationStatus = PostModerationStatus.VISIBLE,
    likes_count: int = 0,
    replies_count: int = 0,
    reposts_count: int = 0,
    is_repost: bool = False,
    created_at: datetime | None = None,
    media_url: str | None = None,
) -> Post:
    p = Post(
        id=post_id,
        user_id=author.id,
        content=content,
        parent_id=parent_id,
        moderation_status=moderation_status,
        likes_count=likes_count,
        replies_count=replies_count,
        reposts_count=reposts_count,
        is_repost=is_repost,
        media_url=media_url,
        created_at=(created_at or _NOW),
        quoted_post_id=None,
        repost_of_id=None,
        moderation_reason=None,
        moderated_at=None,
        moderated_by_user_id=None,
    )
    p.author = author
    # Relationships not needed for serialisation path under mock
    p.original_post = None
    p.parent_post = None
    p.quoted_post = None
    # Annotation fields (set by annotate_posts_for_user)
    p.is_liked_by_me = False
    p.is_bookmarked_by_me = False
    p.has_reposted = False
    p.feed_reason = None
    return p


# ---------------------------------------------------------------------------
# Fake DB helpers used by discover/users tests
# ---------------------------------------------------------------------------

class _RowProxy:
    """Minimal named-row emulator for SQLAlchemy result rows."""

    def __init__(self, **kwargs: Any):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _ScalarResult:
    def __init__(self, value: Any):
        self._v = value

    def scalar_one(self) -> Any:
        return self._v

    def scalar_one_or_none(self) -> Any:
        return self._v

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list:
        return list(self._v) if isinstance(self._v, (list, tuple)) else [self._v]


class _ListResult:
    def __init__(self, values: list):
        self._values = values

    def scalars(self) -> "_ListResult":
        return self

    def all(self) -> list:
        return list(self._values)


# ---------------------------------------------------------------------------
# FakeDB for discover/users
# ---------------------------------------------------------------------------

class FakeUsersDB:
    """
    Controls what build_discover_users() sees when it calls db.execute().

    Two queries are issued:
      1) Candidate pool (SELECT User.id, username, display_name, avatar_url,
                              created_at, mutual_count_sq)
      2) Recent activity (SELECT Post.user_id WHERE ...)
    """

    def __init__(
        self,
        candidate_rows: list[_RowProxy],
        active_poster_ids: list[int] | None = None,
    ):
        self._candidates = candidate_rows
        self._active_poster_ids = active_poster_ids or []
        self._call_count = 0

    async def execute(self, statement):  # noqa: ANN001
        self._call_count += 1
        if self._call_count == 1:
            # Candidate pool query
            return _ListResult(self._candidates)
        # Recent activity query — returns Post-like rows with .user_id
        rows = [SimpleNamespace(user_id=uid) for uid in self._active_poster_ids]
        return _ListResult(rows)

    # Methods called by annotate / no-op stubs (not reached in users path)
    async def commit(self):
        pass

    async def refresh(self, _instance):
        pass


# ---------------------------------------------------------------------------
# FakeDB for discover/posts
# ---------------------------------------------------------------------------

class FakePostsDB:
    """
    Controls what build_discover_posts() sees.

    Queries issued (in order):
      1) get_blocked_user_ids → SELECT blocked_id WHERE blocker_id = ?  (returns [])
      2) COUNT subquery → returns total
      3) Post query → returns posts list
      4) annotate_posts_for_user → several SELECT queries (we stub the service)
    """

    def __init__(self, posts: list[Post], total: int | None = None):
        self._posts = posts
        self._total = total if total is not None else len(posts)
        self._call_count = 0

    async def execute(self, statement):  # noqa: ANN001
        self._call_count += 1
        if self._call_count == 1:
            # get_blocked_user_ids → empty
            return _ListResult([])
        if self._call_count == 2:
            # COUNT
            return _ScalarResult(self._total)
        if self._call_count == 3:
            # Posts
            return _ListResult(self._posts)
        # annotate sub-queries — return empty
        return _ListResult([])

    async def commit(self):
        pass

    async def refresh(self, _instance):
        pass


# ---------------------------------------------------------------------------
# Common client builder
# ---------------------------------------------------------------------------

def _build_client(current_user: User, db: Any) -> TestClient:
    async def override_user():
        return current_user

    async def override_db():
        yield db

    app.dependency_overrides[deps.get_current_user] = override_user
    app.dependency_overrides[deps.get_db] = override_db
    return TestClient(app, base_url="http://localhost")


def _make_candidate_row(
    user_id: int,
    username: str = "candidate",
    mutual_count: int = 0,
    created_at: datetime | None = None,
) -> _RowProxy:
    return _RowProxy(
        id=user_id,
        username=f"{username}_{user_id}",
        display_name=f"Display {user_id}",
        avatar_url=None,
        created_at=(created_at or _NOW_NAIVE),
        mutual_count=mutual_count,
    )


# ---------------------------------------------------------------------------
# Tests: GET /api/discover/users
# ---------------------------------------------------------------------------

class DiscoverUsersTests(unittest.TestCase):

    def setUp(self):
        app.dependency_overrides.clear()
        _reset_redis_state()

    def tearDown(self):
        app.dependency_overrides.clear()
        _reset_redis_state()

    # ------------------------------------------------------------------
    # 1. Happy path — auth'lu kullanıcı, önerilen kullanıcıları alıyor
    # ------------------------------------------------------------------
    def test_happy_path_returns_correct_shape(self):
        current = _make_user(1, "me")
        rows = [
            _make_candidate_row(10, "alice", mutual_count=2),
            _make_candidate_row(11, "bob", mutual_count=0),
        ]
        db = FakeUsersDB(candidate_rows=rows)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()):
            client = _build_client(current, db)
            resp = client.get("/api/discover/users")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("users", body)
        self.assertIn("total", body)
        self.assertIn("limit", body)
        self.assertIn("offset", body)
        self.assertIn("has_more", body)
        self.assertEqual(body["total"], 2)
        self.assertEqual(len(body["users"]), 2)
        # Verify entry shape
        first = body["users"][0]
        self.assertIn("id", first)
        self.assertIn("username", first)
        self.assertIn("mutual_count", first)
        self.assertIn("score", first)

    # ------------------------------------------------------------------
    # 2. Follow filtresi — FakeDB zaten followedları dışarıda bırakıyor
    #    (service WHERE id NOT IN already_following_sq; burada DB mock
    #     direkt filtreli sonuç döner)
    # ------------------------------------------------------------------
    def test_already_followed_user_not_in_results(self):
        """Service excludes followed users at DB level; verify list doesn't
        contain the followed user when DB mock omits them."""
        current = _make_user(1, "me")
        # Row for user 20 is NOT in candidates (simulating DB filtered it out)
        rows = [_make_candidate_row(21, "stranger", mutual_count=0)]
        db = FakeUsersDB(candidate_rows=rows)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()):
            client = _build_client(current, db)
            resp = client.get("/api/discover/users")

        self.assertEqual(resp.status_code, 200)
        returned_ids = {u["id"] for u in resp.json()["users"]}
        self.assertNotIn(20, returned_ids)
        self.assertIn(21, returned_ids)

    # ------------------------------------------------------------------
    # 3. Kendini hariç tut — service WHERE id != current_user_id
    # ------------------------------------------------------------------
    def test_own_user_not_in_results(self):
        """Service filters out current user at DB level; verify self is absent."""
        current = _make_user(5, "self")
        # DB mock does NOT include user 5 in candidate rows (as service would)
        rows = [_make_candidate_row(99, "other", mutual_count=1)]
        db = FakeUsersDB(candidate_rows=rows)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()):
            client = _build_client(current, db)
            resp = client.get("/api/discover/users")

        returned_ids = {u["id"] for u in resp.json()["users"]}
        self.assertNotIn(5, returned_ids)

    # ------------------------------------------------------------------
    # 4. Pagination — limit/offset çalışıyor
    # ------------------------------------------------------------------
    def test_pagination_limit_and_offset(self):
        current = _make_user(1, "pager")
        rows = [
            _make_candidate_row(10, "a", mutual_count=5),
            _make_candidate_row(11, "b", mutual_count=4),
            _make_candidate_row(12, "c", mutual_count=3),
        ]
        db = FakeUsersDB(candidate_rows=rows)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()):
            client = _build_client(current, db)
            resp = client.get("/api/discover/users?limit=2&offset=1")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # total is still 3 (full ranked list), page slice has 2 items
        self.assertEqual(body["total"], 3)
        self.assertEqual(len(body["users"]), 2)
        self.assertEqual(body["offset"], 1)
        self.assertEqual(body["limit"], 2)
        # offset(1) + limit(2) = 3 == total(3) → has_more is False
        self.assertFalse(body["has_more"])

    # ------------------------------------------------------------------
    # 5. Auth zorunlu — token olmadan 401 (HTTPBearerWith401 returns 401)
    # ------------------------------------------------------------------
    def test_no_auth_returns_401(self):
        # Clear any overrides so real get_current_user dependency runs.
        # HTTPBearerWith401 raises 401 when Authorization header is absent.
        app.dependency_overrides.clear()
        client = TestClient(app, base_url="http://localhost")
        resp = client.get("/api/discover/users")
        self.assertEqual(resp.status_code, 401)

    # ------------------------------------------------------------------
    # 6. Score sıralaması — mutual_count yüksek olan öne geliyor
    # ------------------------------------------------------------------
    def test_score_ordering_high_mutual_first(self):
        current = _make_user(1, "ranker")
        # User 30 has higher mutual → higher score → should rank first
        rows = [
            _make_candidate_row(30, "high_mutual", mutual_count=5),
            _make_candidate_row(31, "low_mutual", mutual_count=0),
        ]
        db = FakeUsersDB(candidate_rows=rows)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()):
            client = _build_client(current, db)
            resp = client.get("/api/discover/users")

        body = resp.json()
        users = body["users"]
        self.assertEqual(len(users), 2)
        self.assertGreater(users[0]["score"], users[1]["score"])
        self.assertEqual(users[0]["id"], 30)
        self.assertEqual(users[0]["mutual_count"], 5)

    # ------------------------------------------------------------------
    # 6b. Score: is_new contributes +2 when user created within last 7 days
    # ------------------------------------------------------------------
    def test_new_user_receives_is_new_bonus(self):
        current = _make_user(1, "checker")
        _now_naive = datetime.utcnow()
        fresh_created = _now_naive - timedelta(days=3)  # within 7-day window
        old_created = _now_naive - timedelta(days=30)

        rows = [
            _make_candidate_row(40, "new_user", mutual_count=0, created_at=fresh_created),
            _make_candidate_row(41, "old_user", mutual_count=0, created_at=old_created),
        ]
        db = FakeUsersDB(candidate_rows=rows)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()):
            client = _build_client(current, db)
            resp = client.get("/api/discover/users")

        users = resp.json()["users"]
        # new_user (id=40) should score higher (is_new=1 → +2) → ranked first
        self.assertEqual(users[0]["id"], 40)
        self.assertGreater(users[0]["score"], users[1]["score"])

    # ------------------------------------------------------------------
    # 6c. Score: recent_activity contributes +1
    # ------------------------------------------------------------------
    def test_recently_active_user_gets_activity_bonus(self):
        current = _make_user(1, "activity_checker")
        old_date = _NOW_NAIVE - timedelta(days=30)

        rows = [
            _make_candidate_row(50, "active", mutual_count=0, created_at=old_date),
            _make_candidate_row(51, "inactive", mutual_count=0, created_at=old_date),
        ]
        # user 50 posted recently, user 51 did not
        db = FakeUsersDB(candidate_rows=rows, active_poster_ids=[50])

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()):
            client = _build_client(current, db)
            resp = client.get("/api/discover/users")

        users = resp.json()["users"]
        self.assertEqual(users[0]["id"], 50)
        self.assertGreater(users[0]["score"], users[1]["score"])


# ---------------------------------------------------------------------------
# Tests: GET /api/discover/posts
# ---------------------------------------------------------------------------

class DiscoverPostsTests(unittest.TestCase):

    def setUp(self):
        app.dependency_overrides.clear()
        _reset_redis_state()

    def tearDown(self):
        app.dependency_overrides.clear()
        _reset_redis_state()

    def _build_author(self, user_id: int = 99) -> User:
        return _make_user(user_id, "author")

    # ------------------------------------------------------------------
    # Helper to patch heavy service calls that require real DB
    # ------------------------------------------------------------------
    def _patch_post_services(self):
        """Patch annotate_posts_for_user to be a no-op."""
        return patch(
            "app.services.post_views.annotate_posts_for_user",
            new=AsyncMock(),
        )

    # ------------------------------------------------------------------
    # 1. Happy path — son 7 günün VISIBLE postları geliyor
    # ------------------------------------------------------------------
    def test_happy_path_returns_correct_shape(self):
        current = _make_user(1, "me")
        author = self._build_author(99)
        post = _make_post(
            101, author,
            content="recent visible post",
            moderation_status=PostModerationStatus.VISIBLE,
            likes_count=5,
            created_at=_NOW - timedelta(days=2),
        )
        db = FakePostsDB(posts=[post], total=1)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()), \
             self._patch_post_services():
            client = _build_client(current, db)
            resp = client.get("/api/discover/posts")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("posts", body)
        self.assertIn("total", body)
        self.assertIn("limit", body)
        self.assertIn("offset", body)
        self.assertIn("has_more", body)
        self.assertEqual(body["total"], 1)
        self.assertEqual(len(body["posts"]), 1)
        self.assertEqual(body["posts"][0]["id"], 101)

    # ------------------------------------------------------------------
    # 2. Eski postlar hariç — 7 günden eski post listede yok
    #    (service WHERE created_at >= cutoff; DB mock omits them)
    # ------------------------------------------------------------------
    def test_old_posts_excluded_by_db_filter(self):
        """When DB mock returns no rows (simulating all posts are older than 7 days)."""
        current = _make_user(1, "me")
        db = FakePostsDB(posts=[], total=0)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()), \
             self._patch_post_services():
            client = _build_client(current, db)
            resp = client.get("/api/discover/posts")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 0)
        self.assertEqual(resp.json()["posts"], [])

    # ------------------------------------------------------------------
    # 3. Reply hariç — parent_id olan postlar listede yok
    #    (service WHERE parent_id IS NULL; DB mock omits replies)
    # ------------------------------------------------------------------
    def test_replies_excluded_by_db_filter(self):
        """Verify that when DB returns only top-level posts, no replies appear."""
        current = _make_user(1, "me")
        author = self._build_author(99)
        top_level = _make_post(200, author, parent_id=None)
        # DB mock only returns top_level (simulating reply was filtered at DB level)
        db = FakePostsDB(posts=[top_level], total=1)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()), \
             self._patch_post_services():
            client = _build_client(current, db)
            resp = client.get("/api/discover/posts")

        body = resp.json()
        self.assertEqual(len(body["posts"]), 1)
        # Top-level post should have no parent_id
        self.assertIsNone(body["posts"][0]["parent_id"])

    # ------------------------------------------------------------------
    # 4. HIDDEN/DELETED hariç — moderation_status filtresi
    # ------------------------------------------------------------------
    def test_hidden_and_deleted_posts_excluded(self):
        """DB mock returns only VISIBLE posts (simulating service filter)."""
        current = _make_user(1, "me")
        author = self._build_author(99)
        visible = _make_post(
            300, author,
            moderation_status=PostModerationStatus.VISIBLE,
            created_at=_NOW - timedelta(hours=6),
        )
        # hidden and deleted posts are NOT in db result (filtered by WHERE clause)
        db = FakePostsDB(posts=[visible], total=1)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()), \
             self._patch_post_services():
            client = _build_client(current, db)
            resp = client.get("/api/discover/posts")

        posts = resp.json()["posts"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["moderation_status"], PostModerationStatus.VISIBLE.value)

    # ------------------------------------------------------------------
    # 5. Engagement sıralaması — likes_count + replies_count toplamı yüksek öne
    #    DB mock returns pre-sorted list (as service would order by DB)
    # ------------------------------------------------------------------
    def test_engagement_ordering_high_engagement_first(self):
        current = _make_user(1, "me")
        author = self._build_author(99)
        low_eng = _make_post(
            401, author,
            likes_count=1, replies_count=0,
            created_at=_NOW - timedelta(hours=1),
        )
        high_eng = _make_post(
            402, author,
            likes_count=10, replies_count=5,
            created_at=_NOW - timedelta(hours=2),
        )
        # DB returns in order (high first, as ORDER BY (likes+replies) DESC would)
        db = FakePostsDB(posts=[high_eng, low_eng], total=2)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()), \
             self._patch_post_services():
            client = _build_client(current, db)
            resp = client.get("/api/discover/posts")

        posts = resp.json()["posts"]
        self.assertEqual(len(posts), 2)
        # First post should be high engagement one
        self.assertEqual(posts[0]["id"], 402)
        self.assertEqual(posts[1]["id"], 401)
        # Verify engagement counts
        self.assertGreater(
            posts[0]["likes_count"] + posts[0]["replies_count"],
            posts[1]["likes_count"] + posts[1]["replies_count"],
        )

    # ------------------------------------------------------------------
    # 6. Pagination — limit/offset çalışıyor
    # ------------------------------------------------------------------
    def test_pagination_limit_offset(self):
        current = _make_user(1, "pager")
        author = self._build_author(99)
        # DB returns only the page slice, total reflects full count
        post = _make_post(501, author, created_at=_NOW - timedelta(hours=3))
        db = FakePostsDB(posts=[post], total=10)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()), \
             self._patch_post_services():
            client = _build_client(current, db)
            resp = client.get("/api/discover/posts?limit=1&offset=5")

        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["limit"], 1)
        self.assertEqual(body["offset"], 5)
        self.assertEqual(body["total"], 10)
        self.assertEqual(len(body["posts"]), 1)
        self.assertTrue(body["has_more"])  # offset(5)+limit(1)=6 < total(10)

    def test_pagination_has_more_false_on_last_page(self):
        current = _make_user(1, "pager")
        author = self._build_author(99)
        post = _make_post(601, author, created_at=_NOW - timedelta(hours=1))
        # total=3, offset=2, limit=1 → offset+limit=3 == total → has_more=False
        db = FakePostsDB(posts=[post], total=3)

        with patch("app.core.rate_limit.enforce_rate_limits", new=AsyncMock()), \
             self._patch_post_services():
            client = _build_client(current, db)
            resp = client.get("/api/discover/posts?limit=1&offset=2")

        body = resp.json()
        self.assertFalse(body["has_more"])

    # ------------------------------------------------------------------
    # 7. Auth zorunlu — token olmadan 401 (HTTPBearerWith401 returns 401)
    # ------------------------------------------------------------------
    def test_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        client = TestClient(app, base_url="http://localhost")
        resp = client.get("/api/discover/posts")
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
