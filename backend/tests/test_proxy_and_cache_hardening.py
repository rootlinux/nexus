import os
import secrets
import unittest
import asyncio

from fastapi import Response

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.core.http import (
    TrustedProxyHeadersMiddleware,
    _extract_client_ip_from_forwarded_chain,
    apply_cache_control_headers,
)


class ProxyAndCacheHardeningTests(unittest.TestCase):
    def test_untrusted_peer_cannot_spoof_forwarded_client_ip(self):
        client_ip = _extract_client_ip_from_forwarded_chain(
            peer_ip="198.51.100.10",
            x_forwarded_for="203.0.113.9",
            cf_connecting_ip=None,
            trusted_proxy_cidrs=["173.245.48.0/20"],
        )

        self.assertEqual(client_ip, "198.51.100.10")

    def test_trusted_proxy_chain_uses_real_client_ip(self):
        client_ip = _extract_client_ip_from_forwarded_chain(
            peer_ip="173.245.48.10",
            x_forwarded_for="203.0.113.9, 173.245.48.10",
            cf_connecting_ip="203.0.113.9",
            trusted_proxy_cidrs=["173.245.48.0/20"],
        )

        self.assertEqual(client_ip, "203.0.113.9")

    def test_trusted_proxy_middleware_applies_scheme_host_and_client_ip(self):
        seen_scope = {}

        async def capture_app(scope, receive, send):
            seen_scope.update(scope)

        middleware = TrustedProxyHeadersMiddleware(
            capture_app,
            trusted_proxy_cidrs=["10.0.0.0/8"],
            enabled=True,
        )

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/whoami",
            "raw_path": b"/whoami",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"origin.internal"),
                (b"x-forwarded-for", b"203.0.113.2, 10.0.0.4"),
                (b"x-forwarded-proto", b"https"),
                (b"x-forwarded-host", b"api.example.com"),
            ],
            "client": ("10.0.0.4", 1234),
            "server": ("origin.internal", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            return None

        asyncio.run(middleware(scope, receive, send))

        self.assertEqual(seen_scope["client"][0], "203.0.113.2")
        self.assertEqual(seen_scope["scheme"], "https")
        headers = dict(seen_scope["headers"])
        self.assertEqual(headers[b"host"], b"api.example.com")

    def test_dynamic_api_responses_are_marked_no_store(self):
        response = Response()

        apply_cache_control_headers(
            response,
            path="/api/notifications",
            uploads_prefix="/uploads",
            uploads_cache_control="public, max-age=3600",
        )

        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Pragma"], "no-cache")
        self.assertIn("Authorization", response.headers["Vary"])
        self.assertIn("Cookie", response.headers["Vary"])

    def test_uploaded_media_is_publicly_cacheable_but_upload_errors_are_not(self):
        success = Response(status_code=200)
        failure = Response(status_code=404)

        apply_cache_control_headers(
            success,
            path="/uploads/test.png",
            uploads_prefix="/uploads",
            uploads_cache_control="public, max-age=3600",
        )
        apply_cache_control_headers(
            failure,
            path="/uploads/missing.png",
            uploads_prefix="/uploads",
            uploads_cache_control="public, max-age=3600",
        )

        self.assertEqual(success.headers["Cache-Control"], "public, max-age=3600")
        self.assertEqual(failure.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
