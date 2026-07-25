import asyncio
import os
import secrets
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.services.audit import write_audit_log


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


class AuditServiceContextTests(unittest.TestCase):
    def test_default_actor_type_is_user_for_existing_call_sites(self):
        db = _FakeSession()
        log = asyncio.run(write_audit_log(db, action="password_reset_forced"))
        self.assertEqual(log.actor_type, "user")
        self.assertIsNone(log.service_principal_id)
        self.assertIsNone(log.auth_scopes)

    def test_service_actor_records_principal_and_scopes_not_a_human_role(self):
        db = _FakeSession()
        log = asyncio.run(
            write_audit_log(
                db,
                action="admin_service.delete_user",
                actor_type="service",
                service_principal_id="service-delete",
                auth_scopes=["service:delete"],
                target_type="user",
                target_id=42,
            )
        )
        self.assertEqual(log.actor_type, "service")
        self.assertEqual(log.service_principal_id, "service-delete")
        self.assertEqual(log.auth_scopes, ["service:delete"])
        # actor_role stays reserved for human roles (admin/moderator); a service
        # call with no actor_user must not synthesize a role from it.
        self.assertIsNone(log.actor_role)
        self.assertIsNone(log.actor_user_id)


if __name__ == "__main__":
    unittest.main()
