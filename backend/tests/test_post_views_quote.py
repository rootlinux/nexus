import os
import secrets
import unittest
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from app.models.post import PostModerationStatus
from app.models.user import UserStatus
from app.services.post_views import is_post_visible_to_viewer, post_to_read_schema


def build_user(**overrides):
    base = {
        "id": 1,
        "username": "alice",
        "display_name": "Alice",
        "email": "alice@example.com",
        "avatar_url": None,
        "cover_url": None,
        "bio": None,
        "location": None,
        "website": None,
        "created_at": datetime(2026, 3, 29, 12, 0, 0),
        "is_active": True,
        "status": UserStatus.ACTIVE,
        "banned_at": None,
        "ban_reason": None,
        "status_reason": None,
        "status_changed_at": None,
        "status_changed_by_user_id": None,
        "invited_by_user_id": None,
        "invite_id_used": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def build_post(**overrides):
    author = overrides.pop("author", build_user())
    base = {
        "id": 1,
        "user_id": author.id,
        "content": "hello world",
        "media_url": None,
        "parent_id": None,
        "repost_of_id": None,
        "quoted_post_id": None,
        "is_repost": False,
        "likes_count": 0,
        "replies_count": 0,
        "reposts_count": 0,
        "created_at": datetime(2026, 3, 29, 12, 0, 0),
        "moderation_status": PostModerationStatus.VISIBLE,
        "moderation_reason": None,
        "moderated_at": None,
        "moderated_by_user_id": None,
        "author": author,
        "repost_of": None,
        "parent": None,
        "quoted_post": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class PostViewsQuoteTests(unittest.TestCase):
    def test_post_author_preserves_inviter_details(self):
        inviter = build_user(id=9, username="mentor", display_name="Mentor")
        author = build_user(
            id=2,
            username="bob",
            display_name="Bob",
            email="bob@example.com",
            invited_by_user_id=inviter.id,
            inviter=inviter,
        )
        post = build_post(id=77, author=author, user_id=author.id, content="With lineage")

        serialized = post_to_read_schema(post)

        self.assertIsNotNone(serialized.author.inviter)
        self.assertEqual(serialized.author.inviter.username, "mentor")
        self.assertEqual(serialized.author.inviter.display_name, "Mentor")
        self.assertFalse(hasattr(serialized.author, "email"))
        self.assertFalse(hasattr(serialized.author, "is_admin"))
        self.assertFalse(hasattr(serialized.author, "admin_role"))
        self.assertFalse(hasattr(serialized.author, "status"))
        self.assertFalse(hasattr(serialized.author, "banned_at"))

    def test_visible_reply_serializes_parent_post_context(self):
        parent_author = build_user(id=2, username="bob", display_name="Bob", email="bob@example.com")
        parent_post = build_post(id=12, author=parent_author, user_id=parent_author.id, content="Parent post")
        reply_post = build_post(id=13, content="Reply here", parent_id=parent_post.id, parent=parent_post)

        serialized = post_to_read_schema(reply_post)

        self.assertEqual(serialized.parent_id, 12)
        self.assertIsNotNone(serialized.parent_post)
        self.assertEqual(serialized.parent_post.id, 12)
        self.assertEqual(serialized.parent_post.author.username, "bob")
        self.assertEqual(serialized.parent_post.content, "Parent post")
        self.assertFalse(hasattr(serialized.parent_post.author, "email"))

    def test_hidden_parent_post_does_not_leak_into_reply_context(self):
        parent_author = build_user(id=2, username="bob", display_name="Bob", email="bob@example.com")
        deleted_parent = build_post(
            id=14,
            author=parent_author,
            user_id=parent_author.id,
            content="Should stay hidden",
            moderation_status=PostModerationStatus.DELETED,
        )
        reply_post = build_post(id=15, content="Still visible", parent_id=deleted_parent.id, parent=deleted_parent)

        serialized = post_to_read_schema(reply_post)

        self.assertEqual(serialized.parent_id, 14)
        self.assertIsNone(serialized.parent_post)

    def test_visible_quote_serializes_nested_post(self):
        quoted_author = build_user(id=2, username="bob", display_name="Bob", email="bob@example.com")
        quoted_post = build_post(id=22, author=quoted_author, user_id=quoted_author.id, content="Original post")
        quote_post = build_post(id=33, content="My take", quoted_post_id=quoted_post.id, quoted_post=quoted_post)

        serialized = post_to_read_schema(quote_post)

        self.assertTrue(serialized.is_quote)
        self.assertEqual(serialized.quoted_post_id, 22)
        self.assertIsNotNone(serialized.quoted_post)
        self.assertEqual(serialized.quoted_post.author.username, "bob")
        self.assertFalse(serialized.quoted_post_unavailable)
        self.assertIsNone(serialized.quoted_post_placeholder)

    def test_hidden_quote_target_becomes_tombstone(self):
        quoted_author = build_user(id=2, username="bob", display_name="Bob", email="bob@example.com")
        hidden_post = build_post(
            id=44,
            author=quoted_author,
            user_id=quoted_author.id,
            content="Should not leak",
            moderation_status=PostModerationStatus.DELETED,
        )
        quote_post = build_post(id=55, content="Still visible", quoted_post_id=hidden_post.id, quoted_post=hidden_post)

        serialized = post_to_read_schema(quote_post)

        self.assertTrue(serialized.is_quote)
        self.assertIsNone(serialized.quoted_post)
        self.assertTrue(serialized.quoted_post_unavailable)
        self.assertEqual(serialized.quoted_post_placeholder, "This quoted post is no longer available.")

    def test_post_visibility_helper_checks_author_state(self):
        inactive_author = build_user(is_active=False)
        post = build_post(author=inactive_author, user_id=inactive_author.id)

        self.assertFalse(is_post_visible_to_viewer(post))


if __name__ == "__main__":
    unittest.main()
