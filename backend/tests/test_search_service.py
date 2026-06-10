import os
import secrets
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from app.services.search import _escape_like, _normalize_query, _post_match_rank, _rank_top_posts


def build_post(**overrides):
    base = {
        "id": 1,
        "content": "hello world",
        "likes_count": 3,
        "replies_count": 1,
        "reposts_count": 0,
        "created_at": datetime(2026, 3, 27, 12, 0, 0),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class SearchServiceTests(unittest.TestCase):
    def test_normalize_query_trims_whitespace(self):
        self.assertEqual(_normalize_query("  hello  "), "hello")
        self.assertEqual(_normalize_query("   "), "")

    def test_escape_like_escapes_wildcards(self):
        self.assertEqual(_escape_like(r"100%_match"), r"100\%\_match")

    def test_post_match_rank_prefers_exact_then_prefix_then_contains(self):
        self.assertEqual(_post_match_rank(build_post(content="Hello"), "hello"), 3)
        self.assertEqual(_post_match_rank(build_post(content="Hello there"), "hello"), 2)
        self.assertEqual(_post_match_rank(build_post(content="Say hello there"), "hello"), 1)
        self.assertEqual(_post_match_rank(build_post(content="goodbye"), "hello"), 0)

    def test_rank_top_posts_is_deterministic(self):
        now = datetime(2026, 3, 27, 12, 0, 0)
        exact = build_post(id=10, content="hello", created_at=now - timedelta(hours=8), likes_count=0, replies_count=0, reposts_count=0)
        prefix = build_post(id=11, content="hello from x", created_at=now - timedelta(hours=1), likes_count=10, replies_count=2, reposts_count=1)
        contains_a = build_post(id=12, content="say hello", created_at=now - timedelta(hours=2), likes_count=4, replies_count=1, reposts_count=1)
        contains_b = build_post(id=13, content="say hello", created_at=now - timedelta(hours=2), likes_count=4, replies_count=1, reposts_count=1)

        ranked = _rank_top_posts([contains_a, prefix, exact, contains_b], query="hello", now=now)

        self.assertEqual([item.post.id for item in ranked], [10, 11, 13, 12])


if __name__ == "__main__":
    unittest.main()
