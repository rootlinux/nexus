import os
import secrets
import unittest

from fastapi import HTTPException, Request, Response

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from app.api.routes.auth import (
    _build_token_response,
    _clear_refresh_cookie,
    _get_refresh_token_from_request,
    _prefers_cookie_refresh,
    _set_refresh_cookie,
)
from app.core.config import settings
from app.schemas.auth import Token


def build_request(headers: dict[bytes, bytes] | None = None, cookies: str | None = None) -> Request:
    raw_headers = list((headers or {}).items())
    if cookies is not None:
        raw_headers.append((b"cookie", cookies.encode()))

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/refresh",
        "headers": raw_headers,
    }
    return Request(scope)


class AuthCookieSessionTests(unittest.TestCase):
    def setUp(self):
        self._original_secure = settings.REFRESH_COOKIE_SECURE
        self._original_domain = settings.REFRESH_COOKIE_DOMAIN

    def tearDown(self):
        settings.REFRESH_COOKIE_SECURE = self._original_secure
        settings.REFRESH_COOKIE_DOMAIN = self._original_domain

    def test_cookie_transport_header_switches_response_to_cookie_mode(self):
        request = build_request(headers={b"x-session-transport": b"cookie"})
        tokens = Token(access_token="access", refresh_token="refresh")

        response = _build_token_response(tokens, request)

        self.assertTrue(_prefers_cookie_refresh(request))
        self.assertEqual(response.access_token, "access")
        self.assertIsNone(response.refresh_token)

    def test_refresh_token_can_be_read_from_cookie_when_body_is_empty(self):
        request = build_request(cookies=f"{settings.REFRESH_COOKIE_NAME}=cookie-token")

        refresh_token = _get_refresh_token_from_request(request, None)

        self.assertEqual(refresh_token, "cookie-token")

    def test_missing_refresh_token_raises_unauthorized(self):
        request = build_request()

        with self.assertRaises(HTTPException) as context:
            _get_refresh_token_from_request(request, None)

        self.assertEqual(context.exception.status_code, 401)

    def test_refresh_cookie_is_set_and_cleared_with_auth_path(self):
        settings.REFRESH_COOKIE_SECURE = True
        settings.REFRESH_COOKIE_DOMAIN = "example.com"

        response = Response()
        _set_refresh_cookie(response, "refresh-token")
        set_cookie_header = response.headers.get("set-cookie", "")

        self.assertIn(f"{settings.REFRESH_COOKIE_NAME}=refresh-token", set_cookie_header)
        self.assertIn("HttpOnly", set_cookie_header)
        self.assertIn("Path=/api/auth", set_cookie_header)
        self.assertIn("Secure", set_cookie_header)
        self.assertIn("Domain=example.com", set_cookie_header)

        response = Response()
        _clear_refresh_cookie(response)
        clear_cookie_header = response.headers.get("set-cookie", "")

        self.assertIn(f"{settings.REFRESH_COOKIE_NAME}=", clear_cookie_header)
        self.assertIn("Path=/api/auth", clear_cookie_header)
        self.assertIn("Secure", clear_cookie_header)
        self.assertIn("Domain=example.com", clear_cookie_header)


if __name__ == "__main__":
    unittest.main()
