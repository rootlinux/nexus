from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Iterable

from starlette.responses import PlainTextResponse
from starlette.datastructures import MutableHeaders


def _parse_trusted_networks(values: Iterable[str]) -> list:
    networks = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        try:
            if "/" in normalized:
                networks.append(ip_network(normalized, strict=False))
            else:
                networks.append(ip_network(f"{normalized}/32", strict=False))
        except ValueError:
            continue
    return networks


def _ip_in_trusted_networks(value: str | None, trusted_networks: list) -> bool:
    if not value:
        return False
    try:
        parsed = ip_address(value.strip())
    except ValueError:
        return False
    return any(parsed in network for network in trusted_networks)


def _split_header_values(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _extract_forwarded_host(value: str | None) -> str | None:
    forwarded_hosts = _split_header_values(value)
    if not forwarded_hosts:
        return None
    return forwarded_hosts[0]


def _extract_forwarded_proto(value: str | None) -> str | None:
    forwarded_protocols = _split_header_values(value)
    if not forwarded_protocols:
        return None
    candidate = forwarded_protocols[0].lower()
    if candidate in {"http", "https", "ws", "wss"}:
        return candidate
    return None


def _extract_client_ip_from_forwarded_chain(
    *,
    peer_ip: str | None,
    x_forwarded_for: str | None,
    cf_connecting_ip: str | None,
    trusted_proxy_cidrs: Iterable[str],
) -> str | None:
    trusted_networks = _parse_trusted_networks(trusted_proxy_cidrs)
    if not _ip_in_trusted_networks(peer_ip, trusted_networks):
        return peer_ip

    forwarded_chain = _split_header_values(x_forwarded_for)
    for hop in reversed(forwarded_chain):
        if not _ip_in_trusted_networks(hop, trusted_networks):
            return hop

    if forwarded_chain:
        return forwarded_chain[0]

    if cf_connecting_ip and not _ip_in_trusted_networks(cf_connecting_ip, trusted_networks):
        return cf_connecting_ip.strip()

    return peer_ip


class TrustedProxyHeadersMiddleware:
    def __init__(self, app, *, trusted_proxy_cidrs: Iterable[str], enabled: bool) -> None:
        self.app = app
        self.enabled = enabled
        self.trusted_proxy_cidrs = [item.strip() for item in trusted_proxy_cidrs if item.strip()]
        self.trusted_networks = _parse_trusted_networks(self.trusted_proxy_cidrs)

    async def __call__(self, scope, receive, send) -> None:
        if not self.enabled or scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        peer_ip = client[0] if client else None
        if not _ip_in_trusted_networks(peer_ip, self.trusted_networks):
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)

        forwarded_proto = _extract_forwarded_proto(headers.get("x-forwarded-proto"))
        if forwarded_proto:
            if scope["type"] == "websocket":
                scope["scheme"] = "wss" if forwarded_proto == "https" else "ws"
            else:
                scope["scheme"] = forwarded_proto

        forwarded_host = _extract_forwarded_host(headers.get("x-forwarded-host"))
        if forwarded_host:
            headers["host"] = forwarded_host
            if ":" in forwarded_host:
                host, _, port = forwarded_host.rpartition(":")
                try:
                    scope["server"] = (host, int(port))
                except ValueError:
                    scope["server"] = (forwarded_host, 0)
            else:
                default_port = 443 if scope.get("scheme") in {"https", "wss"} else 80
                scope["server"] = (forwarded_host, default_port)

        client_ip = _extract_client_ip_from_forwarded_chain(
            peer_ip=peer_ip,
            x_forwarded_for=headers.get("x-forwarded-for"),
            cf_connecting_ip=headers.get("cf-connecting-ip"),
            trusted_proxy_cidrs=self.trusted_proxy_cidrs,
        )
        if client_ip:
            scope["client"] = (client_ip, 0)

        await self.app(scope, receive, send)


def _normalize_host(value: str | None) -> str:
    if not value:
        return ""
    host = value.strip().lower()
    if host.startswith("[") and "]" in host:
        return host[1:host.index("]")]
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def _host_matches_pattern(host: str, pattern: str) -> bool:
    normalized_pattern = pattern.strip().lower()
    if not normalized_pattern:
        return False
    if normalized_pattern == "*":
        return True
    if normalized_pattern.startswith("*."):
        suffix = normalized_pattern[1:]
        return host.endswith(suffix) and host != suffix[1:]
    return host == _normalize_host(normalized_pattern)


class HostValidationMiddleware:
    def __init__(self, app, *, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        self.allowed_hosts = [host.strip() for host in allowed_hosts if host.strip()]

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in {"http", "websocket"} or not self.allowed_hosts:
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        host_header = headers.get("host")
        normalized_host = _normalize_host(host_header)

        if any(_host_matches_pattern(normalized_host, pattern) for pattern in self.allowed_hosts):
            await self.app(scope, receive, send)
            return

        response = PlainTextResponse("Invalid host header", status_code=400)
        await response(scope, receive, send)


class RequestBodySizeLimitMiddleware:
    """ASGI-level streaming body-size guard. This is the actual enforcement
    point for upload size limits — Starlette's multipart parser has no
    file-part size cap of its own, so a route-level read-limit helper alone
    would run after the entire body has already been parsed (and, past
    spool_max_size, spooled to disk).

    Correction (discovered via this task's own real-server verification,
    not assumed): the original design raised a custom exception from inside
    guarded_receive() and relied on it unwinding cleanly back up to this
    middleware's own try/except. That is fragile in practice — FastAPI's own
    body-parsing code (fastapi.routing's request_body_to_args) wraps
    `await request.form()` in a broad `except Exception` that converts
    anything else into a generic `HTTPException(400, "There was an error
    parsing the body")`, silently swallowing a plain Exception before it
    ever reaches this middleware. Making the exception an HTTPException
    subclass so FastAPI's own `except HTTPException: raise` preserves it
    was tried and STILL failed once real middleware layers (CORS, the
    security-headers BaseHTTPMiddleware, etc.) sat between this guard and
    Starlette's ExceptionMiddleware — empirically, exception-based unwinding
    through that stack is not reliable, only reproducible in a bare
    two-middleware toy setup.

    The robust fix does not rely on exception propagation at all: once the
    streamed total exceeds the limit, this middleware sends the 413 response
    itself, directly, through the real `send` it was given — bypassing
    whatever the downstream app (FastAPI, mid-dependency-resolution) is
    doing entirely — then tells the downstream the client disconnected
    (`http.disconnect`, the standard ASGI signal for "stop, nothing more is
    coming") so it unwinds on its own without needing a special exception
    type to survive. `guarded_send` independently guarantees no double
    response: once the guard has fired, every further message the
    downstream still tries to emit (its own error response, a stray
    success response race, anything) is silently discarded rather than
    forwarded to the real client."""

    def __init__(self, app, *, path_limits: dict[str, int]) -> None:
        self.app = app
        self.path_limits = path_limits

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"].rstrip("/") or "/"
        limit = self.path_limits.get(path)
        if limit is None:
            await self.app(scope, receive, send)
            return

        declared = _parse_content_length(MutableHeaders(scope=scope).get("content-length"))
        if declared is not None and declared > limit:
            await _send_413(send)
            return

        total = 0
        guard_tripped = False
        downstream_response_started = False

        async def guarded_receive():
            nonlocal total, guard_tripped
            if guard_tripped:
                # Already handled (413 already sent) — tell the downstream
                # nothing more is coming, rather than pulling more bytes off
                # a connection we're done with.
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    guard_tripped = True
                    if not downstream_response_started:
                        await _send_413(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            nonlocal downstream_response_started
            if guard_tripped:
                # We've already fully responded (or deliberately chosen not
                # to, because the downstream beat us to it) — never forward
                # anything further to the real client.
                return
            if message["type"] == "http.response.start":
                downstream_response_started = True
            await send(message)

        await self.app(scope, guarded_receive, guarded_send)


async def _send_413(send) -> None:
    body = b'{"detail":"Uploaded file is too large."}'
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"connection", b"close"),
        ],
    })
    await send({"type": "http.response.body", "body": body})


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def is_no_store_path(path: str) -> bool:
    if path == "/health":
        return True
    if not path.startswith("/api"):
        return False
    return True


def apply_cache_control_headers(response, *, path: str, uploads_prefix: str, uploads_cache_control: str) -> None:
    normalized_uploads_prefix = uploads_prefix.rstrip("/") or "/uploads"

    if path.startswith(normalized_uploads_prefix):
        if response.status_code >= 400:
            response.headers["Cache-Control"] = "no-store"
        elif "cache-control" not in response.headers:
            response.headers["Cache-Control"] = uploads_cache_control
        return

    if is_no_store_path(path):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        vary_values = {"authorization", "cookie"}
        existing_vary = response.headers.get("Vary", "")
        for value in _split_header_values(existing_vary):
            vary_values.add(value.lower())
        response.headers["Vary"] = ", ".join(sorted(value.title() for value in vary_values))
