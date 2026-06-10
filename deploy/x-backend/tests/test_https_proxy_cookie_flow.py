import os
import secrets
import socket
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Request, Response
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("ALLOWED_HOSTS", "127.0.0.1,localhost")
os.environ.setdefault("TRUST_PROXY_HEADERS", "true")
os.environ.setdefault("TRUSTED_PROXY_CIDRS", "127.0.0.1")

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_password_hash
from app.main import app
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserStatus
from app.models.webauthn_credential import WebAuthnCredential


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _wait_for_ready(url: str, *, verify: bool = True, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with httpx.Client(verify=verify, timeout=1.0) as client:
                response = client.get(url)
            if response.status_code < 500:
                return
        except Exception:
            time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {url}")


def _write_self_signed_cert(cert_path: Path, key_path: Path) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Local Proxy Test"),
            x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


class _ScalarResult:
    def __init__(self, value: Any):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        if self._value is None:
            raise AssertionError("Expected a value")
        return self._value


class _FakeDBSession:
    def __init__(self) -> None:
        self.user = User(
            id=1,
            username="proxyuser",
            display_name="Proxy User",
            email="proxy@example.com",
            password_hash=get_password_hash("correct-horse-battery-staple"),
            created_at=datetime.now(timezone.utc),
            is_active=True,
            status=UserStatus.ACTIVE,
            email_verified_at=datetime.now(timezone.utc),
        )
        self._refresh_tokens_by_hash: dict[str, RefreshToken] = {}
        self._next_refresh_id = 1

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        params = statement.compile().params

        if entity is User:
            requested_user_id = next((value for key, value in params.items() if "id" in key), self.user.id)
            if requested_user_id == self.user.id:
                return _ScalarResult(self.user)
            return _ScalarResult(None)

        if entity is RefreshToken:
            token_id = next((value for key, value in params.items() if key == "id_1"), None)
            token_hash = next((value for key, value in params.items() if "token_hash" in key), None)
            if token_id is not None:
                token = next((item for item in self._refresh_tokens_by_hash.values() if item.id == int(token_id)), None)
                return _ScalarResult(token)
            return _ScalarResult(self._refresh_tokens_by_hash.get(token_hash))

        if entity is WebAuthnCredential:
            return _ScalarResult(None)

        raise AssertionError(f"Unexpected statement entity: {entity}")

    def add(self, instance):
        if isinstance(instance, RefreshToken):
            if instance.id is None:
                instance.id = self._next_refresh_id
                self._next_refresh_id += 1
            self._refresh_tokens_by_hash[instance.token_hash] = instance

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def close(self):
        return None


def _build_proxy_app(backend_base_url: str) -> FastAPI:
    proxy_app = FastAPI()

    @proxy_app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def proxy(path: str, request: Request) -> Response:
        forwarded_headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in {"host", "connection", "content-length"}
        }
        forwarded_headers["host"] = request.headers.get("host", "")
        forwarded_headers["x-forwarded-proto"] = "https"
        forwarded_headers["x-forwarded-for"] = "203.0.113.10, 127.0.0.1"
        forwarded_headers["x-forwarded-host"] = request.headers.get("host", "")

        query = f"?{request.url.query}" if request.url.query else ""
        async with httpx.AsyncClient(base_url=backend_base_url, follow_redirects=False, timeout=10.0) as client:
            upstream = await client.request(
                request.method,
                f"/{path}{query}",
                headers=forwarded_headers,
                content=await request.body(),
            )

        excluded_headers = {"connection", "content-length", "keep-alive", "transfer-encoding"}
        response_headers = {
            name: value
            for name, value in upstream.headers.items()
            if name.lower() not in excluded_headers
        }
        return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)

    return proxy_app


class HttpsProxyCookieFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._original_cookie_secure = settings.REFRESH_COOKIE_SECURE
        cls._original_app_env = settings.APP_ENV
        cls._original_allowed_hosts = list(settings.ALLOWED_HOSTS)
        cls._original_trust_proxy_headers = settings.TRUST_PROXY_HEADERS
        cls._original_trusted_proxy_cidrs = list(settings.TRUSTED_PROXY_CIDRS)
        settings.REFRESH_COOKIE_SECURE = True
        settings.APP_ENV = "test"
        settings.ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
        settings.TRUST_PROXY_HEADERS = True
        settings.TRUSTED_PROXY_CIDRS = ["127.0.0.1"]

        cls._db = _FakeDBSession()
        cls._original_overrides = dict(app.dependency_overrides)

        async def override_db():
            yield cls._db

        async def _noop_rate_limit(*args, **kwargs):
            return None

        async def _noop_audit_log(*args, **kwargs):
            return None

        cls._rate_limit_patch = patch("app.api.routes.auth.enforce_rate_limits", new=_noop_rate_limit)
        cls._audit_patch = patch("app.api.routes.auth.write_audit_log", new=_noop_audit_log)
        cls._rate_limit_patch.start()
        cls._audit_patch.start()
        app.dependency_overrides[get_db] = override_db

        cls.backend_port = _pick_free_port()
        cls.proxy_port = _pick_free_port()
        cls.backend_base_url = f"http://127.0.0.1:{cls.backend_port}"
        cls.proxy_base_url = f"https://127.0.0.1:{cls.proxy_port}"

        config = uvicorn.Config(app, host="127.0.0.1", port=cls.backend_port, log_level="warning")
        cls._uvicorn_server = uvicorn.Server(config)
        cls._backend_thread = threading.Thread(target=cls._uvicorn_server.run, daemon=True)
        cls._backend_thread.start()
        _wait_for_ready(f"{cls.backend_base_url}/health")

        cls._cert_dir = tempfile.TemporaryDirectory()
        cert_path = Path(cls._cert_dir.name) / "cert.pem"
        key_path = Path(cls._cert_dir.name) / "key.pem"
        _write_self_signed_cert(cert_path, key_path)

        proxy_app = _build_proxy_app(cls.backend_base_url)
        proxy_config = uvicorn.Config(
            proxy_app,
            host="127.0.0.1",
            port=cls.proxy_port,
            log_level="warning",
            ssl_keyfile=str(key_path),
            ssl_certfile=str(cert_path),
        )
        cls._proxy_server = uvicorn.Server(proxy_config)
        cls._proxy_thread = threading.Thread(target=cls._proxy_server.run, daemon=True)
        cls._proxy_thread.start()
        _wait_for_ready(f"{cls.proxy_base_url}/health", verify=False)

    @classmethod
    def tearDownClass(cls):
        settings.REFRESH_COOKIE_SECURE = cls._original_cookie_secure
        settings.APP_ENV = cls._original_app_env
        settings.ALLOWED_HOSTS = cls._original_allowed_hosts
        settings.TRUST_PROXY_HEADERS = cls._original_trust_proxy_headers
        settings.TRUSTED_PROXY_CIDRS = cls._original_trusted_proxy_cidrs
        app.dependency_overrides = cls._original_overrides
        cls._rate_limit_patch.stop()
        cls._audit_patch.stop()

        cls._proxy_server.should_exit = True
        cls._proxy_thread.join(timeout=5)

        cls._uvicorn_server.should_exit = True
        cls._backend_thread.join(timeout=5)

        cls._cert_dir.cleanup()

    def _cookie_values(self, client: httpx.Client) -> list[str]:
        return [
            cookie.value
            for cookie in client.cookies.jar
            if cookie.name == settings.REFRESH_COOKIE_NAME
        ]

    def test_secure_refresh_cookie_survives_https_proxy_login_refresh_and_logout(self):
        with httpx.Client(base_url=self.proxy_base_url, verify=False, timeout=10.0) as client:
            login_response = client.post(
                "/api/auth/login",
                headers={"X-Session-Transport": "cookie"},
                json={"username": "proxyuser", "password": "correct-horse-battery-staple"},
            )

            self.assertEqual(login_response.status_code, 200)
            self.assertIn("access_token", login_response.json())
            self.assertIsNone(login_response.json()["refresh_token"])
            self.assertIn("Secure", login_response.headers.get("set-cookie", ""))

            login_cookie_values = self._cookie_values(client)
            self.assertEqual(len(login_cookie_values), 1)
            self.assertTrue(
                any(
                    cookie.name == settings.REFRESH_COOKIE_NAME and cookie.secure
                    for cookie in client.cookies.jar
                )
            )

            me_response = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {login_response.json()['access_token']}"},
            )
            self.assertEqual(me_response.status_code, 200)
            self.assertEqual(me_response.json()["username"], "proxyuser")

            direct_http_refresh = httpx.post(
                f"{self.backend_base_url}/api/auth/refresh",
                headers={"X-Session-Transport": "cookie"},
                json={},
                cookies=client.cookies,
                timeout=10.0,
            )
            self.assertEqual(direct_http_refresh.status_code, 401)

            refresh_response = client.post(
                "/api/auth/refresh",
                headers={"X-Session-Transport": "cookie"},
                json={},
            )

            self.assertEqual(refresh_response.status_code, 200)
            self.assertIn("access_token", refresh_response.json())
            self.assertIsNone(refresh_response.json()["refresh_token"])
            self.assertNotEqual(login_cookie_values, self._cookie_values(client))

            refreshed_me = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {refresh_response.json()['access_token']}"},
            )
            self.assertEqual(refreshed_me.status_code, 200)
            self.assertEqual(refreshed_me.json()["email"], "proxy@example.com")

            logout_response = client.post("/api/auth/logout", json={})
            self.assertEqual(logout_response.status_code, 204)
            self.assertEqual(self._cookie_values(client), [])

            post_logout_refresh = client.post(
                "/api/auth/refresh",
                headers={"X-Session-Transport": "cookie"},
                json={},
            )
            self.assertEqual(post_logout_refresh.status_code, 401)


if __name__ == "__main__":
    unittest.main()
