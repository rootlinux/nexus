import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from app.services.feed_ranking import (  # noqa: E402
    FeedRankingContext,
    ModerationSignalSummary,
    rank_home_feed_candidates,
)


def build_author(**overrides):
    base = {
        "id": 1,
        "username": "author",
        "display_name": "Author",
        "avatar_url": None,
        "invited_by_user_id": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def build_post(**overrides):
    author = overrides.pop("author", build_author())
    base = {
        "id": 1,
        "user_id": author.id,
        "author": author,
        "content": "hello world",
        "media_url": None,
        "likes_count": 1,
        "replies_count": 0,
        "reposts_count": 0,
        "created_at": datetime(2026, 3, 27, 12, 0, 0),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def build_context(**overrides):
    base = {
        "current_user_id": 99,
        "current_user_invited_by_user_id": 7,
        "following_ids": frozenset(),
        "second_degree_ids": frozenset(),
        "author_signal_map": {},
        "post_signal_map": {},
    }
    base.update(overrides)
    return FeedRankingContext(**base)


class FeedRankingServiceTests(unittest.TestCase):
    def test_legacy_naive_post_timestamps_are_normalized_for_aware_feed_ranking(self):
        aware_now = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)
        legacy_post = build_post(
            id=5,
            created_at=datetime(2026, 3, 27, 10, 0, 0),
            likes_count=2,
        )

        ranked = rank_home_feed_candidates([legacy_post], build_context(), now=aware_now)

        self.assertEqual([item.post.id for item in ranked], [5])
        self.assertGreaterEqual(ranked[0].breakdown.freshness_score, 0)

    def test_followed_authors_rank_above_outside_network_posts(self):
        now = datetime(2026, 3, 27, 12, 0, 0)
        followed_author = build_author(id=2, invited_by_user_id=8)
        outside_author = build_author(id=3)
        followed_post = build_post(
            id=10,
            author=followed_author,
            created_at=now - timedelta(hours=4),
            likes_count=2,
        )
        outside_post = build_post(
            id=11,
            author=outside_author,
            created_at=now - timedelta(minutes=20),
            likes_count=20,
            replies_count=8,
            reposts_count=6,
        )

        ranked = rank_home_feed_candidates(
            [outside_post, followed_post],
            build_context(following_ids=frozenset({2})),
            now=now,
        )

        self.assertEqual([item.post.id for item in ranked], [10, 11])
        self.assertEqual(ranked[0].feed_reason, "From people you follow")

    def test_second_degree_and_invite_lineage_get_network_reason(self):
        now = datetime(2026, 3, 27, 12, 0, 0)
        network_author = build_author(id=4, invited_by_user_id=12)
        network_post = build_post(
            id=21,
            author=network_author,
            created_at=now - timedelta(hours=2),
            likes_count=5,
            replies_count=2,
        )

        ranked = rank_home_feed_candidates(
            [network_post],
            build_context(
                following_ids=frozenset({12}),
                second_degree_ids=frozenset({4}),
            ),
            now=now,
        )

        self.assertEqual(ranked[0].feed_reason, "Popular in your network")

    def test_moderation_history_dampens_suspicious_authors(self):
        now = datetime(2026, 3, 27, 12, 0, 0)
        trusted_author = build_author(id=5)
        suspicious_author = build_author(id=6)
        trusted_post = build_post(
            id=31,
            author=trusted_author,
            created_at=now - timedelta(hours=3),
            likes_count=3,
            replies_count=1,
        )
        suspicious_post = build_post(
            id=32,
            author=suspicious_author,
            created_at=now - timedelta(hours=1),
            likes_count=6,
            replies_count=3,
        )

        ranked = rank_home_feed_candidates(
            [suspicious_post, trusted_post],
            build_context(
                author_signal_map={
                    6: ModerationSignalSummary(
                        open_suspicious_count=2,
                        resolved_suspicious_count=1,
                    )
                }
            ),
            now=now,
        )

        self.assertEqual([item.post.id for item in ranked], [31, 32])

    def test_ranking_is_deterministic_for_ties(self):
        now = datetime(2026, 3, 27, 12, 0, 0)
        first = build_post(id=41, created_at=now - timedelta(hours=5), likes_count=3)
        second = build_post(id=42, created_at=now - timedelta(hours=5), likes_count=3)

        ranked = rank_home_feed_candidates([first, second], build_context(), now=now)

        self.assertEqual([item.post.id for item in ranked], [42, 41])


if __name__ == "__main__":
    unittest.main()
