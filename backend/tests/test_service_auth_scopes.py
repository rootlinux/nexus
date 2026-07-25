import asyncio
import os
import secrets
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from fastapi import HTTPException

from app.api.dependencies import service_auth
from app.core.config import settings


class ServiceAuthScopeTests(unittest.TestCase):
    def setUp(self):
        self._original = {
            "ADMIN_SERVICE_TOKEN": settings.ADMIN_SERVICE_TOKEN,
            "SERVICE_TOKEN_READ": settings.SERVICE_TOKEN_READ,
            "SERVICE_TOKEN_NOTIFY": settings.SERVICE_TOKEN_NOTIFY,
            "SERVICE_TOKEN_DELETE": settings.SERVICE_TOKEN_DELETE,
        }
        settings.ADMIN_SERVICE_TOKEN = ""
        settings.SERVICE_TOKEN_READ = ""
        settings.SERVICE_TOKEN_NOTIFY = ""
        settings.SERVICE_TOKEN_DELETE = ""

    def tearDown(self):
        for key, value in self._original.items():
            setattr(settings, key, value)

    def _call(self, dependency, token):
        return asyncio.run(dependency(token=token))

    def test_missing_token_rejected(self):
        dependency = service_auth.require_service_scope(service_auth.SCOPE_READ)
        with self.assertRaises(HTTPException) as ctx:
            self._call(dependency, "")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_unconfigured_scope_rejects_any_token(self):
        # No SERVICE_TOKEN_READ and no legacy ADMIN_SERVICE_TOKEN configured:
        # the read scope must fail closed, not silently accept anything.
        dependency = service_auth.require_service_scope(service_auth.SCOPE_READ)
        with self.assertRaises(HTTPException):
            self._call(dependency, "anything")

    def test_scoped_token_grants_only_its_own_scope(self):
        settings.SERVICE_TOKEN_READ = "read-token-value"
        read_dep = service_auth.require_service_scope(service_auth.SCOPE_READ)
        delete_dep = service_auth.require_service_scope(service_auth.SCOPE_DELETE)

        context = self._call(read_dep, "read-token-value")
        self.assertEqual(context.principal_id, "service-read")
        self.assertEqual(context.scopes, frozenset({service_auth.SCOPE_READ}))

        with self.assertRaises(HTTPException):
            self._call(delete_dep, "read-token-value")

    def test_wrong_token_value_rejected(self):
        settings.SERVICE_TOKEN_READ = "correct-token"
        dependency = service_auth.require_service_scope(service_auth.SCOPE_READ)
        with self.assertRaises(HTTPException):
            self._call(dependency, "wrong-token")

    def test_legacy_admin_token_grants_all_three_scopes(self):
        settings.ADMIN_SERVICE_TOKEN = "legacy-token"
        for scope in (service_auth.SCOPE_READ, service_auth.SCOPE_NOTIFY, service_auth.SCOPE_DELETE):
            dependency = service_auth.require_service_scope(scope)
            context = self._call(dependency, "legacy-token")
            self.assertEqual(context.principal_id, "legacy-admin-service")
            self.assertIn(scope, context.scopes)

    def test_scoped_and_legacy_tokens_can_coexist(self):
        settings.ADMIN_SERVICE_TOKEN = "legacy-token"
        settings.SERVICE_TOKEN_DELETE = "delete-token"
        dependency = service_auth.require_service_scope(service_auth.SCOPE_DELETE)

        scoped_context = self._call(dependency, "delete-token")
        self.assertEqual(scoped_context.principal_id, "service-delete")

        legacy_context = self._call(dependency, "legacy-token")
        self.assertEqual(legacy_context.principal_id, "legacy-admin-service")


if __name__ == "__main__":
    unittest.main()
