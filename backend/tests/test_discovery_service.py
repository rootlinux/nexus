import os
import secrets
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from app.services.discovery import (
    _merge_for_you_rankings,
    _rank_trending_posts,
    _sort_ranked_posts,
    compute_trending_score,
    derive_category_label,
)


def build_post(**overrides):
    base = {
        "id": 1,
        "content": "hello world",
        "media_url": None,
        "likes_count": 1,
        "replies_count": 0,
        "reposts_count": 0,
        "created_at": datetime(2026, 3, 27, 12, 0, 0),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class DiscoveryServiceTests(unittest.TestCase):
    def test_trending_score_rewards_more_recent_posts(self):
        now = datetime(2026, 3, 27, 12, 0, 0)
        fresh_post = build_post(created_at=now - timedelta(hours=2), likes_count=5, replies_count=1, reposts_count=1)
        older_post = build_post(id=2, created_at=now - timedelta(hours=10), likes_count=5, replies_count=1, reposts_count=1)

        self.assertGreater(
            compute_trending_score(fresh_post, now, window_hours=48),
            compute_trending_score(older_post, now, window_hours=48),
        )

    def test_category_label_uses_existing_post_signals(self):
        self.assertEqual(derive_category_label(build_post(media_url="/uploads/pic.jpg")), "With media")
        self.assertEqual(derive_category_label(build_post(likes_count=1, replies_count=4, reposts_count=1)), "Conversation")
        self.assertEqual(derive_category_label(build_post(likes_count=2, replies_count=1, reposts_count=5)), "Shared widely")
        self.assertEqual(derive_category_label(build_post(likes_count=3, replies_count=0, reposts_count=0)), "Popular")

    def test_ranked_posts_are_sorted_deterministically(self):
        now = datetime(2026, 3, 27, 12, 0, 0)
        first = build_post(id=11, created_at=now - timedelta(hours=4), likes_count=5, replies_count=2, reposts_count=1)
        second = build_post(id=12, created_at=now - timedelta(hours=4), likes_count=5, replies_count=2, reposts_count=1)
        third = build_post(id=13, created_at=now - timedelta(hours=1), likes_count=0, replies_count=0, reposts_count=0)

        ranked = _rank_trending_posts([first, second, third], now=now, window_hours=48)
        ordered = _sort_ranked_posts(ranked)

        self.assertEqual([item.post.id for item in ordered], [12, 11])

    def test_for_you_merge_keeps_followed_posts_ahead_of_fallback(self):
        now = datetime(2026, 3, 27, 12, 0, 0)
        followed = [
            SimpleNamespace(post=build_post(id=21, created_at=now - timedelta(hours=3)), score=25, discovery_reason="From people you follow")
        ]
        fallback = [
            SimpleNamespace(post=build_post(id=22, created_at=now - timedelta(minutes=30)), score=400, discovery_reason="Trending beyond your circle"),
            SimpleNamespace(post=build_post(id=23, created_at=now - timedelta(minutes=45)), score=300, discovery_reason="Trending beyond your circle"),
        ]

        merged = _merge_for_you_rankings(followed, fallback, limit=3)

        self.assertEqual([item.post.id for item in merged], [21, 22, 23])


if __name__ == "__main__":
    unittest.main()
