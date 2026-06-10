import os
import unittest
from types import SimpleNamespace

from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.api.dm import _enforce_dm_target_available, _normalize_message_content
from app.models.user import UserStatus


class DirectMessagePolicyTests(unittest.TestCase):
    def test_normalize_message_content_trims_text(self):
        self.assertEqual(_normalize_message_content("  hello there  "), "hello there")

    def test_normalize_message_content_rejects_whitespace_only(self):
        with self.assertRaises(HTTPException) as context:
            _normalize_message_content("   ")

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Message cannot be empty.")

    def test_target_availability_rejects_frozen_user(self):
        user = SimpleNamespace(status=UserStatus.FROZEN, is_active=True)

        with self.assertRaises(HTTPException) as context:
            _enforce_dm_target_available(user)

        self.assertEqual(context.exception.status_code, 403)
        self.assertEqual(context.exception.detail, "This account can't receive messages right now.")

    def test_target_availability_rejects_inactive_user(self):
        user = SimpleNamespace(status=UserStatus.ACTIVE, is_active=False)

        with self.assertRaises(HTTPException) as context:
            _enforce_dm_target_available(user)

        self.assertEqual(context.exception.status_code, 403)
        self.assertEqual(context.exception.detail, "This account can't receive messages right now.")


if __name__ == "__main__":
    unittest.main()
