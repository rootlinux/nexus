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
            "SERVICE_TOKEN_READ": settings.SERVICE_TOKEN_READ,
            "SERVICE_TOKEN_NOTIFY": settings.SERVICE_TOKEN_NOTIFY,
            "SERVICE_TOKEN_DELETE": settings.SERVICE_TOKEN_DELETE,
        }
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
        # No SERVICE_TOKEN_READ configured: the read scope has no valid credential at
        # all and must fail closed, not silently accept anything.
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

    def test_removed_legacy_admin_service_token_cannot_authenticate(self):
        # The all-scopes ADMIN_SERVICE_TOKEN / ENABLE_LEGACY_ADMIN_SERVICE_TOKEN pair was
        # removed outright. A deployment that still exports those values gets no access:
        # the settings fields no longer exist, and the credential they held is just an
        # unknown token to every scope.
        self.assertFalse(hasattr(settings, "ADMIN_SERVICE_TOKEN"))
        self.assertFalse(hasattr(settings, "ENABLE_LEGACY_ADMIN_SERVICE_TOKEN"))

        settings.SERVICE_TOKEN_READ = "read-token-value"
        for scope in (service_auth.SCOPE_READ, service_auth.SCOPE_NOTIFY, service_auth.SCOPE_DELETE):
            dependency = service_auth.require_service_scope(scope)
            with self.assertRaises(HTTPException) as ctx:
                self._call(dependency, "legacy-token")
            self.assertEqual(ctx.exception.status_code, 403)

    def test_read_credential_cannot_notify_or_delete(self):
        # Least privilege, stated as a test rather than a convention: the read credential
        # is the one nexus-mcp is issued, and it must be inert on the mutating scopes even
        # when those scopes have their own credentials configured.
        settings.SERVICE_TOKEN_READ = "read-token-value"
        settings.SERVICE_TOKEN_NOTIFY = "notify-token-value"
        settings.SERVICE_TOKEN_DELETE = "delete-token-value"

        for scope in (service_auth.SCOPE_NOTIFY, service_auth.SCOPE_DELETE):
            dependency = service_auth.require_service_scope(scope)
            with self.assertRaises(HTTPException) as ctx:
                self._call(dependency, "read-token-value")
            self.assertEqual(ctx.exception.status_code, 403)

    def test_every_scope_fails_closed_when_no_credentials_configured(self):
        for scope in (service_auth.SCOPE_READ, service_auth.SCOPE_NOTIFY, service_auth.SCOPE_DELETE):
            dependency = service_auth.require_service_scope(scope)
            for candidate in ("", "guess", "legacy-token"):
                with self.assertRaises(HTTPException) as ctx:
                    self._call(dependency, candidate)
                self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
