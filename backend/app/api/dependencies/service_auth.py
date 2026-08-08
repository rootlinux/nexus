import logging
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.core.config import settings

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-Service-Token", auto_error=False)

SCOPE_READ = "service:read"
SCOPE_NOTIFY = "service:notify"
SCOPE_DELETE = "service:delete"


@dataclass(frozen=True)
class ServiceAuthContext:
    principal_id: str
    scopes: frozenset[str]

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def _scoped_credentials() -> dict[str, tuple[str, str]]:
    """scope -> (token, principal_id) for explicitly configured scoped credentials."""
    candidates = {
        SCOPE_READ: (settings.SERVICE_TOKEN_READ, "service-read"),
        SCOPE_NOTIFY: (settings.SERVICE_TOKEN_NOTIFY, "service-notify"),
        SCOPE_DELETE: (settings.SERVICE_TOKEN_DELETE, "service-delete"),
    }
    return {scope: value for scope, value in candidates.items() if value[0]}


def _match_scoped_token(provided: str, required_scope: str) -> ServiceAuthContext | None:
    entry = _scoped_credentials().get(required_scope)
    if entry and secrets.compare_digest(provided, entry[0]):
        return ServiceAuthContext(principal_id=entry[1], scopes=frozenset({required_scope}))
    return None


def require_service_scope(required_scope: str):
    """FastAPI dependency factory: authenticate via X-Service-Token and require `required_scope`.

    The only credential that can satisfy a scope is that scope's own token
    (SERVICE_TOKEN_READ / SERVICE_TOKEN_NOTIFY / SERVICE_TOKEN_DELETE). There is no
    combined credential and no fallback: presenting the read token to a delete endpoint
    is rejected exactly like an unknown token, and a scope whose token is unset has no
    valid credential at all. Fails closed when the header is missing.
    """

    async def dependency(token: str = Security(api_key_header)) -> ServiceAuthContext:
        provided = token or ""
        if not provided:
            # Never log the token itself — only that one was missing/invalid and which
            # scope was being requested.
            logger.warning("Service auth rejected: no X-Service-Token provided (scope=%s)", required_scope)
            raise HTTPException(status_code=403, detail="Invalid or missing service token")

        context = _match_scoped_token(provided, required_scope)
        if context is None:
            logger.warning(
                "Service auth rejected: token did not match required scope=%s (scope_configured=%s)",
                required_scope,
                required_scope in _scoped_credentials(),
            )
            raise HTTPException(status_code=403, detail="Invalid or missing service token")

        return context

    return dependency
