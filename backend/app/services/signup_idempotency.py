from __future__ import annotations

import json
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.services.account_security import normalize_email

logger = logging.getLogger(__name__)


class SignupIdempotencyService:
    LOCK_TTL = 30
    RESULT_TTL = 300

    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    def _request_lock_key(self, request_key: str) -> str:
        return f"signup:lock:{request_key}"

    def _fingerprint_lock_key(self, invite_code: str, email: str, username: str) -> str:
        normalized_invite = invite_code.strip()
        normalized_email = normalize_email(email)
        normalized_username = username.strip()
        return f"signup:fp:{normalized_invite}:{normalized_email}:{normalized_username}"

    def _result_key(self, request_key: str) -> str:
        return f"signup:result:{request_key}"

    async def get_cached_result(self, request_key: str) -> dict | None:
        try:
            cached = await self.redis.get(self._result_key(request_key))
        except RedisError:
            logger.warning("Failed to read cached signup result from Redis.", exc_info=True)
            return None

        if cached is None:
            return None

        try:
            value = json.loads(cached)
        except json.JSONDecodeError:
            logger.warning("Failed to decode cached signup result payload.")
            return None

        return value if isinstance(value, dict) else None

    async def acquire_locks(
        self,
        request_key: str | None,
        invite_code: str,
        email: str,
        username: str,
    ) -> tuple[bool, bool]:
        request_lock_acquired = False
        try:
            if request_key is not None:
                request_lock_acquired = bool(
                    await self.redis.set(
                        self._request_lock_key(request_key),
                        "1",
                        ex=self.LOCK_TTL,
                        nx=True,
                    )
                )
                if not request_lock_acquired:
                    return False, False

            fingerprint_lock_acquired = bool(
                await self.redis.set(
                    self._fingerprint_lock_key(invite_code, email, username),
                    "1",
                    ex=self.LOCK_TTL,
                    nx=True,
                )
            )
            if not fingerprint_lock_acquired:
                if request_lock_acquired and request_key is not None:
                    await self.redis.delete(self._request_lock_key(request_key))
                return False, False

            return True, True
        except RedisError:
            logger.warning("Failed to acquire signup idempotency locks from Redis.", exc_info=True)
            return True, True

    async def release_locks(
        self,
        request_key: str | None,
        invite_code: str,
        email: str,
        username: str,
    ) -> None:
        keys = [self._fingerprint_lock_key(invite_code, email, username)]
        if request_key is not None:
            keys.append(self._request_lock_key(request_key))

        try:
            await self.redis.delete(*keys)
        except RedisError:
            logger.warning("Failed to release signup idempotency locks from Redis.", exc_info=True)

    async def cache_result(self, request_key: str | None, result: dict) -> None:
        if request_key is None:
            return

        try:
            await self.redis.set(
                self._result_key(request_key),
                json.dumps(result),
                ex=self.RESULT_TTL,
            )
        except RedisError:
            logger.warning("Failed to cache signup result in Redis.", exc_info=True)
            return
