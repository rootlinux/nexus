"""Real-server verification for Round 2, Task 1's upload body-size guard.

Runs the actual FastAPI app under a real `uvicorn` subprocess (and, where a
`caddy` binary is available, a disposable Caddy instance fronting it using
the Step 7 path-matcher config) and drives it with raw sockets, since a real
HTTP client can't be made to lie about Content-Length or omit it while
streaming a known body. This is heavier than the rest of the suite —
excluded from fast local iteration via the `real_server` marker, but still
required and run explicitly before this task's commit.

Per the fourth amendment's correction to this file: an understated
Content-Length is NOT expected to produce a 413. uvicorn/h11 frames the
request body strictly to the declared length — bytes beyond it are never
delivered to the ASGI app at all — so that scenario is verified via
protocol rejection/connection closure and the smuggling/desync check
instead, never via a 413 assertion.
"""

import asyncio
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.core.config import settings  # noqa: E402 — must follow the env defaults above

pytestmark = pytest.mark.real_server


@pytest.fixture(scope="module", autouse=True)
def _clear_feedback_ip_rate_limit():
    """This module hits /api/feedback/report's IP-sustained rate limit
    (10/hour, keyed by the loopback address every test in this file uses)
    several times per run. Repeated runs within the same hour would
    otherwise accumulate against a real Redis instance and fail with an
    unrelated 429 instead of exercising the size guard — clear only this
    file's own narrowly-scoped keys before starting, never a blanket flush."""
    import hashlib

    try:
        import redis as redis_sync
    except ImportError:
        yield
        return

    ip_hash = hashlib.md5(b"127.0.0.1").hexdigest()[:16]
    pattern = f"rate-limit:sliding:feedback:report:ip:{ip_hash}:sustained:*"
    try:
        client = redis_sync.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        keys = list(client.scan_iter(match=pattern))
        if keys:
            client.delete(*keys)
        client.close()
    except Exception:
        pass  # best-effort only — a real failure here will surface as a 429 in the tests themselves
    yield

BACKEND_DIR = Path(__file__).resolve().parents[1]

ROUTE_LIMIT_ENV = {
    "/api/users/me/avatar": "AVATAR_UPLOAD_MAX_BYTES",
    "/api/users/me/cover": "COVER_UPLOAD_MAX_BYTES",
    "/api/posts/upload-image": "POST_IMAGE_UPLOAD_MAX_BYTES",
    "/api/feedback/report": "FEEDBACK_ATTACHMENT_MAX_BYTES",
}

# The multipart field name each route's file parameter is bound to — needed so
# Starlette's form parser actually engages (and therefore keeps calling
# receive(), which is what lets the ASGI size guard observe the streamed
# bytes) instead of short-circuiting on an unrecognized/non-multipart body.
ROUTE_FIELD_NAME = {
    "/api/users/me/avatar": "file",
    "/api/users/me/cover": "file",
    "/api/posts/upload-image": "file",
    "/api/feedback/report": "attachment",
}

_MULTIPART_BOUNDARY = "----Round2RealServerTestBoundary"

DEFAULT_LIMITS = {
    "AVATAR_UPLOAD_MAX_BYTES": 5 * 1024 * 1024,
    "COVER_UPLOAD_MAX_BYTES": 8 * 1024 * 1024,
    "POST_IMAGE_UPLOAD_MAX_BYTES": 5 * 1024 * 1024,
    "FEEDBACK_ATTACHMENT_MAX_BYTES": 5 * 1024 * 1024,
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_http(host: str, port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0) as s:
                s.sendall(f"GET /health HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
                data = s.recv(4096)
                if data.startswith(b"HTTP/1.1"):
                    return
        except OSError as exc:
            last_exc = exc
        time.sleep(0.2)
    raise RuntimeError(f"server at {host}:{port} did not become ready: {last_exc}")


def _read_response(sock: socket.socket, timeout: float = 5.0):
    """Returns (status_code, headers dict, body bytes) or (None, {}, partial bytes)
    if the connection closed / timed out before a complete response arrived."""
    sock.settimeout(timeout)
    data = b""
    try:
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    except (socket.timeout, ConnectionError):
        pass

    if b"\r\n\r\n" not in data:
        return None, {}, data

    header_blob, _, rest = data.partition(b"\r\n\r\n")
    lines = header_blob.split(b"\r\n")
    try:
        status_code = int(lines[0].decode(errors="replace").split(" ")[1])
    except (IndexError, ValueError):
        return None, {}, data

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if b":" in line:
            key, _, value = line.partition(b":")
            headers[key.decode().strip().lower()] = value.decode().strip()

    body = rest
    content_length = headers.get("content-length")
    if content_length is not None:
        needed = int(content_length) - len(body)
        try:
            while needed > 0:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                body += chunk
                needed -= len(chunk)
        except (socket.timeout, ConnectionError):
            pass

    return status_code, headers, body


def _format_extra_headers(extra_headers: dict[str, str] | None) -> str:
    if not extra_headers:
        return ""
    return "".join(f"{key}: {value}\r\n" for key, value in extra_headers.items())


def _multipart_part_header(field_name: str) -> bytes:
    return (
        f"--{_MULTIPART_BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="big.bin"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()


def _multipart_closing_boundary() -> bytes:
    return f"\r\n--{_MULTIPART_BOUNDARY}--\r\n".encode()


def _send_chunked_oversized(
    host: str, port: int, path: str, total_bytes: int, *, extra_headers: dict[str, str] | None = None,
    field_name: str = "file",
) -> socket.socket:
    """Streams a genuine multipart/form-data envelope (so Starlette's form
    parser actually engages and keeps calling receive(), which is what lets
    the ASGI guard observe the streamed bytes) whose single file field's
    content alone exceeds the limit, via chunked Transfer-Encoding."""
    sock = socket.create_connection((host, port), timeout=5.0)
    request = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Transfer-Encoding: chunked\r\n"
        f"Content-Type: multipart/form-data; boundary={_MULTIPART_BOUNDARY}\r\n"
        f"{_format_extra_headers(extra_headers)}"
        "\r\n"
    )
    sock.sendall(request.encode())

    def _send_chunk(data: bytes) -> bool:
        """Returns False if the peer has already closed the connection (the
        expected outcome once the size guard trips and stops draining) —
        callers stop sending further chunks once this happens."""
        if not data:
            return True
        try:
            sock.sendall(f"{len(data):x}\r\n".encode() + data + b"\r\n")
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    if not _send_chunk(_multipart_part_header(field_name)):
        return sock

    remaining = total_bytes
    piece_size = 65536
    while remaining > 0:
        this_piece = min(piece_size, remaining)
        if not _send_chunk(b"a" * this_piece):
            return sock  # server already closed the connection (e.g. after a 413) — stop sending
        remaining -= this_piece
    _send_chunk(_multipart_closing_boundary())
    try:
        sock.sendall(b"0\r\n\r\n")
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    return sock


def _send_understated_content_length(
    host: str, port: int, path: str, declared_length: int, actual_body: bytes,
    *, extra_headers: dict[str, str] | None = None,
) -> socket.socket:
    sock = socket.create_connection((host, port), timeout=5.0)
    request = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Content-Length: {declared_length}\r\n"
        "Content-Type: application/octet-stream\r\n"
        f"{_format_extra_headers(extra_headers)}"
        "\r\n"
    )
    try:
        sock.sendall(request.encode() + actual_body)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass  # server closed the connection before/while we sent the trailing bytes — acceptable
    return sock


def _assert_no_desync_on_reused_connection(sock: socket.socket, host: str) -> None:
    """After a prior response on this connection, either the socket is already
    closed (consistent with Connection: close), or a fresh well-formed request
    gets its own correct, undisturbed response."""
    try:
        sock.sendall(f"GET /health HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
    except (BrokenPipeError, ConnectionResetError, OSError):
        return  # socket already closed — expected/acceptable outcome

    status_code, _headers, body = _read_response(sock, timeout=3.0)
    if status_code is None:
        return  # connection closed mid-read — also acceptable (no garbled response)

    # If a response WAS received, it must be a clean, correct /health response —
    # never garbled, truncated, or bled-over from the previous request's body.
    assert status_code == 200, f"expected a clean 200 for the follow-up request, got {status_code}"
    assert b"ok" in body or b"alive" in body, f"follow-up response body looks corrupted: {body!r}"


@pytest.fixture(scope="module")
def disposable_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — point this at the session's disposable Postgres container")
    return url


@pytest.fixture(scope="module")
def upload_dirs():
    with tempfile.TemporaryDirectory() as uploads_dir, tempfile.TemporaryDirectory() as feedback_dir:
        yield Path(uploads_dir), Path(feedback_dir)


@pytest.fixture(scope="module")
def backend_server(disposable_database_url, upload_dirs):
    uploads_dir, feedback_dir = upload_dirs
    port = _free_port()
    env = os.environ.copy()
    env["DATABASE_URL"] = disposable_database_url
    env.setdefault("REDIS_URL", "redis://localhost:6379/0")
    # Same SECRET_KEY the test process's own `settings` uses, so a JWT minted in
    # the test process (auth_headers fixture) verifies correctly in the subprocess.
    env["SECRET_KEY"] = settings.SECRET_KEY
    env["LOCAL_UPLOAD_DIR"] = str(uploads_dir)
    env["FEEDBACK_ATTACHMENT_LOCAL_DIR"] = str(feedback_dir)
    env["APP_ENV"] = "test"

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=str(BACKEND_DIR), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_http("127.0.0.1", port)
        yield {"host": "127.0.0.1", "port": port, "uploads_dir": uploads_dir, "feedback_dir": feedback_dir}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="function")
def auth_headers(disposable_database_url, backend_server) -> dict[str, str]:
    """A real, DB-backed user + a JWT signed with the same SECRET_KEY the
    subprocess uses. Function-scoped (a fresh user per test), not module-
    scoped: /api/feedback/report's own rate limiting is keyed by user id
    (3 requests / 600s burst policy) — sharing one user across every test in
    this module that hits that route would trip the limit by the 4th test
    and produce a 429 unrelated to anything this file is actually testing.
    Required in the first place because the ASGI body-size guard only gets
    exercised once downstream code actually tries to read the request body —
    an unauthenticated request fails at the auth dependency first and never
    reaches that code, which would make these tests pass for the wrong
    reason (401, not 413)."""
    import bcrypt
    from datetime import datetime

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    from app.core.security import create_access_token
    import app.models.webauthn_credential  # noqa: F401 — registers the mapper User.webauthn_credentials resolves by string name
    from app.models.user import User, UserStatus

    async def _create_user() -> int:
        engine = create_async_engine(disposable_database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            user = User(
                username=f"real-server-{secrets.token_hex(4)}",
                email=f"real-server-{secrets.token_hex(4)}@example.com",
                password_hash=bcrypt.hashpw(b"irrelevant", bcrypt.gensalt()).decode(),
                status=UserStatus.ACTIVE,
                is_active=True,
                # Must be fully "interactive"-eligible (verified email, active, not
                # banned/suspended/frozen) so the ONLY way these requests can fail is
                # the body-size guard — otherwise an auth-layer 403/401 can race the
                # guard and win depending on network timing (observed via Caddy's
                # extra hop), producing a false negative unrelated to the size guard.
                email_verified_at=datetime.utcnow(),  # naive — the column is DateTime without timezone
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            user_id = user.id
        await engine.dispose()
        return user_id

    user_id = asyncio.run(_create_user())
    token = create_access_token({"sub": str(user_id), "username": "real-server-user"})
    return {"Authorization": f"Bearer {token}"}


def _caddy_available() -> bool:
    return shutil.which("caddy") is not None


@pytest.fixture(scope="module")
def caddy_server(backend_server):
    if not _caddy_available():
        pytest.skip("caddy binary not available")

    caddy_port = _free_port()
    backend_port = backend_server["port"]
    caddyfile_text = textwrap.dedent(f"""\
        {{
            auto_https off
            admin off
        }}
        :{caddy_port} {{
            @avatar_upload {{
                path /api/users/me/avatar /api/users/me/avatar/
            }}
            handle @avatar_upload {{
                request_body {{
                    max_size 5300KB
                }}
                reverse_proxy 127.0.0.1:{backend_port}
            }}
            @cover_upload {{
                path /api/users/me/cover /api/users/me/cover/
            }}
            handle @cover_upload {{
                request_body {{
                    max_size 8450KB
                }}
                reverse_proxy 127.0.0.1:{backend_port}
            }}
            @post_image_upload {{
                path /api/posts/upload-image /api/posts/upload-image/
            }}
            handle @post_image_upload {{
                request_body {{
                    max_size 5300KB
                }}
                reverse_proxy 127.0.0.1:{backend_port}
            }}
            @feedback_report_upload {{
                path /api/feedback/report /api/feedback/report/
            }}
            handle @feedback_report_upload {{
                request_body {{
                    max_size 5300KB
                }}
                reverse_proxy 127.0.0.1:{backend_port}
            }}
            handle {{
                reverse_proxy 127.0.0.1:{backend_port}
            }}
        }}
    """)

    with tempfile.NamedTemporaryFile("w", suffix=".Caddyfile", delete=False) as fh:
        fh.write(caddyfile_text)
        caddyfile_path = fh.name

    proc = subprocess.Popen(
        ["caddy", "run", "--config", caddyfile_path, "--adapter", "caddyfile"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_http("127.0.0.1", caddy_port)
        yield {"host": "127.0.0.1", "port": caddy_port}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        os.unlink(caddyfile_path)


def _all_files(*dirs: Path) -> set[str]:
    found: set[str] = set()
    for d in dirs:
        for root, _dirnames, filenames in os.walk(d):
            for name in filenames:
                found.add(os.path.join(root, name))
    return found


@pytest.mark.parametrize("route,limit_env_key", list(ROUTE_LIMIT_ENV.items()))
class TestRealServerUploadLimits:
    def test_chunked_no_content_length_oversized_gets_exactly_one_413(
        self, backend_server, auth_headers, route, limit_env_key,
    ):
        limit = DEFAULT_LIMITS[limit_env_key]
        before = _all_files(backend_server["uploads_dir"], backend_server["feedback_dir"])

        sock = _send_chunked_oversized(
            backend_server["host"], backend_server["port"], route, limit + settings.UPLOAD_GUARD_OVERHEAD_BYTES + 4096,
            extra_headers=auth_headers, field_name=ROUTE_FIELD_NAME[route],
        )
        status_code, _headers, _body = _read_response(sock)
        assert status_code == 413

        # Exactly one response — reading again must not yield a second 413/200.
        second_status, _h2, _b2 = _read_response(sock, timeout=1.0)
        assert second_status is None or second_status == 413  # closed, or same response already fully drained

        _assert_no_desync_on_reused_connection(sock, backend_server["host"])
        sock.close()

        after = _all_files(backend_server["uploads_dir"], backend_server["feedback_dir"])
        assert after == before, "oversized chunked upload must never reach storage"

    def test_understated_content_length_is_not_asserted_413_but_is_safe(
        self, backend_server, auth_headers, route, limit_env_key,
    ):
        limit = DEFAULT_LIMITS[limit_env_key]
        before = _all_files(backend_server["uploads_dir"], backend_server["feedback_dir"])

        declared = min(1024, limit - 1)  # honestly under the limit
        actual_body = b"a" * (limit + 4096)  # far more bytes than declared

        sock = _send_understated_content_length(
            backend_server["host"], backend_server["port"], route, declared, actual_body,
            extra_headers=auth_headers,
        )
        # No assertion on the status code here at all — the framed (declared-length)
        # portion may succeed or fail depending on route semantics, and that's not
        # what this test is checking. What's required: no smuggling/desync, and no
        # storage write from the unframed trailing bytes.
        _read_response(sock, timeout=3.0)
        _assert_no_desync_on_reused_connection(sock, backend_server["host"])
        sock.close()

        after = _all_files(backend_server["uploads_dir"], backend_server["feedback_dir"])
        assert after == before, "understated-Content-Length trailing bytes must never reach storage"

    def test_trailing_slash_variant_oversized_never_uploads(
        self, backend_server, auth_headers, route, limit_env_key,
    ):
        limit = DEFAULT_LIMITS[limit_env_key]
        before = _all_files(backend_server["uploads_dir"], backend_server["feedback_dir"])

        sock = _send_chunked_oversized(
            backend_server["host"], backend_server["port"], route + "/", limit + settings.UPLOAD_GUARD_OVERHEAD_BYTES + 4096,
            extra_headers=auth_headers, field_name=ROUTE_FIELD_NAME[route],
        )
        status_code, headers, _body = _read_response(sock)
        # 413 (guard fires) and 404 (no matching route) are the two outcomes the
        # plan anticipated. In practice, Starlette's default redirect_slashes
        # behavior can also produce a 307 for a trailing-slash path that isn't
        # itself registered but matches a registered path without the slash —
        # this happens BEFORE the body is ever read (no receive() calls occur for
        # a redirect), so it's a real, safe third outcome: no upload can occur
        # from a 307, and its Location must still point at a guarded path.
        assert status_code in (413, 404, 307), f"unexpected status for trailing-slash variant: {status_code}"
        if status_code == 307:
            from urllib.parse import urlparse

            location_path = urlparse(headers.get("location", "")).path
            assert location_path.rstrip("/") == route, f"307 redirect target must be the same guarded canonical path, got {location_path!r}"
        sock.close()

        after = _all_files(backend_server["uploads_dir"], backend_server["feedback_dir"])
        assert after == before, "trailing-slash oversized upload must never reach storage"

    def test_caddy_fronted_chunked_oversized_gets_413(self, caddy_server, auth_headers, route, limit_env_key):
        limit = DEFAULT_LIMITS[limit_env_key]
        sock = _send_chunked_oversized(
            caddy_server["host"], caddy_server["port"], route, limit + settings.UPLOAD_GUARD_OVERHEAD_BYTES + 4096,
            extra_headers=auth_headers, field_name=ROUTE_FIELD_NAME[route],
        )
        status_code, _headers, _body = _read_response(sock)
        assert status_code == 413
        sock.close()
