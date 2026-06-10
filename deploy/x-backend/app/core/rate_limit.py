from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from dataclasses import dataclass
from typing import Literal, Sequence

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)

RATE_LIMIT_ERROR = "You're doing that too often. Please wait and try again."
AUTH_RATE_LIMIT_ERROR = "Too many attempts. Please try again shortly."
RATE_LIMIT_BACKEND_ERROR = "This action is temporarily unavailable. Please try again shortly."

RateLimitStrategy = Literal["fixed_window", "sliding_window"]


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    limit: int
    window_seconds: int
    key: str
    message: str = RATE_LIMIT_ERROR
    strategy: RateLimitStrategy = "fixed_window"
    require_redis_in_production: bool = False


class RateLimitBackendUnavailable(Exception):
    def __init__(self, policy: RateLimitPolicy) -> None:
        self.policy = policy
        super().__init__(policy.name)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    backend: str


class _MemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._fixed_counters: dict[str, tuple[int, float]] = {}
        self._sliding_counters: dict[str, tuple[int, int, int, int]] = {}

    async def hit(
        self,
        key: str,
        limit: int,
        window_seconds: int,
        strategy: RateLimitStrategy,
    ) -> RateLimitResult:
        if strategy == "sliding_window":
            return await self._hit_sliding_window(key, limit, window_seconds)
        return await self._hit_fixed_window(key, limit, window_seconds)

    async def _hit_fixed_window(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.time()
        retry_after = window_seconds
        async with self._lock:
            count, reset_at = self._fixed_counters.get(key, (0, now + window_seconds))
            if reset_at <= now:
                count = 0
                reset_at = now + window_seconds

            count += 1
            self._fixed_counters[key] = (count, reset_at)
            retry_after = max(1, math.ceil(reset_at - now))

        return RateLimitResult(
            allowed=count <= limit,
            limit=limit,
            remaining=max(0, limit - count),
            retry_after=retry_after,
            backend="memory",
        )

    async def _hit_sliding_window(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.time()
        current_bucket = int(now // window_seconds)
        elapsed_in_bucket = now - (current_bucket * window_seconds)
        previous_weight = max(0.0, 1 - (elapsed_in_bucket / window_seconds))

        async with self._lock:
            state = self._sliding_counters.get(key)
            if state is None:
                prev_bucket = current_bucket - 1
                prev_count = 0
                active_bucket = current_bucket
                active_count = 0
            else:
                prev_bucket, prev_count, active_bucket, active_count = state

            if active_bucket != current_bucket:
                if active_bucket == current_bucket - 1:
                    prev_bucket = active_bucket
                    prev_count = active_count
                else:
                    prev_bucket = current_bucket - 1
                    prev_count = 0
                active_bucket = current_bucket
                active_count = 0

            if prev_bucket != current_bucket - 1:
                prev_bucket = current_bucket - 1
                prev_count = 0

            active_count += 1
            self._sliding_counters[key] = (prev_bucket, prev_count, active_bucket, active_count)

        weighted_total = active_count + (prev_count * previous_weight)
        retry_after = max(1, math.ceil(window_seconds - elapsed_in_bucket))
        return RateLimitResult(
            allowed=weighted_total <= limit,
            limit=limit,
            remaining=max(0, math.floor(limit - weighted_total)),
            retry_after=retry_after,
            backend="memory",
        )


_memory_rate_limiter = _MemoryRateLimiter()
_redis_client: Redis | None = None
_redis_lock = asyncio.Lock()


async def _get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    async with _redis_lock:
        if _redis_client is None:
            _redis_client = Redis.from_url(
                    settings.REDIS_URL,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=3,
                    max_connections=20,
                )
        return _redis_client


def get_client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def hash_key_part(value: str | int | None) -> str:
    # MD5 is intentionally used here: rate-limit keys are non-cryptographic
    # identifiers (obfuscated email/IP for Redis keys). MD5 is ~3× faster than
    # SHA-256 and collision resistance is irrelevant for this use case.
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "none"
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]  # noqa: S324


def build_scope_key(*parts: str | int | None) -> str:
    normalized_parts = [str(part).strip() for part in parts if part not in (None, "")]
    return ":".join(normalized_parts) if normalized_parts else "global"


def _is_production_mode() -> bool:
    return settings.APP_ENV.strip().lower() in {"production", "prod", "release"}


async def _hit_redis_fixed_window(key: str, limit: int, window_seconds: int) -> RateLimitResult:
    now = time.time()
    window_bucket = int(now // window_seconds)
    redis_key = f"rate-limit:{key}:{window_bucket}"
    client = await _get_redis_client()
    count = await client.incr(redis_key)
    if count == 1:
        await client.expire(redis_key, window_seconds)
    ttl = await client.ttl(redis_key)
    retry_after = max(1, ttl if ttl and ttl > 0 else window_seconds - int(now % window_seconds))
    return RateLimitResult(
        allowed=count <= limit,
        limit=limit,
        remaining=max(0, limit - count),
        retry_after=retry_after,
        backend="redis",
    )


async def _hit_redis_sliding_window(key: str, limit: int, window_seconds: int) -> RateLimitResult:
    now = time.time()
    current_bucket = int(now // window_seconds)
    elapsed_in_bucket = now - (current_bucket * window_seconds)
    previous_weight = max(0.0, 1 - (elapsed_in_bucket / window_seconds))
    current_key = f"rate-limit:sliding:{key}:{current_bucket}"
    previous_key = f"rate-limit:sliding:{key}:{current_bucket - 1}"
    client = await _get_redis_client()

    pipeline = client.pipeline(transaction=True)
    pipeline.incr(current_key)
    pipeline.expire(current_key, window_seconds * 2)
    pipeline.get(previous_key)
    current_count, _, previous_count_raw = await pipeline.execute()
    previous_count = int(previous_count_raw or 0)
    weighted_total = current_count + (previous_count * previous_weight)
    retry_after = max(1, math.ceil(window_seconds - elapsed_in_bucket))
    return RateLimitResult(
        allowed=weighted_total <= limit,
        limit=limit,
        remaining=max(0, math.floor(limit - weighted_total)),
        retry_after=retry_after,
        backend="redis",
    )


async def _hit_redis_limit(policy: RateLimitPolicy) -> RateLimitResult:
    if policy.strategy == "sliding_window":
        return await _hit_redis_sliding_window(policy.key, policy.limit, policy.window_seconds)
    return await _hit_redis_fixed_window(policy.key, policy.limit, policy.window_seconds)


async def get_redis_client() -> Redis:
    return await _get_redis_client()


async def hit_rate_limit(policy: RateLimitPolicy) -> RateLimitResult:
    try:
        return await _hit_redis_limit(policy)
    except RedisError:
        if policy.require_redis_in_production and _is_production_mode():
            logger.error(
                "Redis rate limit backend unavailable for Redis-required policy",
                extra={"policy": policy.name},
                exc_info=True,
            )
            raise RateLimitBackendUnavailable(policy)

        logger.warning(
            "Redis rate limit backend unavailable. Falling back to in-memory counters.",
            extra={"policy": policy.name},
            exc_info=True,
        )
        return await _memory_rate_limiter.hit(policy.key, policy.limit, policy.window_seconds, policy.strategy)


async def enforce_rate_limits(request: Request, policies: Sequence[RateLimitPolicy]) -> None:
    for policy in policies:
        try:
            result = await hit_rate_limit(policy)
        except RateLimitBackendUnavailable:
            request_id = getattr(request.state, "request_id", None)
            logger.error(
                "Rate limiting backend unavailable for protected route",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "policy": policy.name,
                    "client_ip": get_client_ip(request),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=RATE_LIMIT_BACKEND_ERROR,
                headers={"Retry-After": "30"},
            )
        if result.allowed:
            continue

        request_id = getattr(request.state, "request_id", None)
        logger.warning(
            "Rate limit exceeded",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "policy": policy.name,
                "backend": result.backend,
                "client_ip": get_client_ip(request),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=policy.message,
            headers={
                "Retry-After": str(result.retry_after),
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": str(result.remaining),
                "X-RateLimit-Policy": policy.name,
            },
        )
