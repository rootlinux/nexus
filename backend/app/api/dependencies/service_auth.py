import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.core.config import settings

api_key_header = APIKeyHeader(name="X-Service-Token", auto_error=False)

SCOPE_READ = "service:read"
SCOPE_NOTIFY = "service:notify"
SCOPE_DELETE = "service:delete"
_LEGACY_TOKEN_SCOPES = frozenset({SCOPE_READ, SCOPE_NOTIFY, SCOPE_DELETE})


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


def _match_legacy_token(provided: str, required_scope: str) -> ServiceAuthContext | None:
    legacy_token = settings.ADMIN_SERVICE_TOKEN
    if legacy_token and secrets.compare_digest(provided, legacy_token):
        return ServiceAuthContext(principal_id="legacy-admin-service", scopes=_LEGACY_TOKEN_SCOPES)
    return None


def require_service_scope(required_scope: str):
    """FastAPI dependency factory: authenticate via X-Service-Token and require `required_scope`.

    Prefers a scoped credential (SERVICE_TOKEN_READ/NOTIFY/DELETE) for the exact scope.
    Falls back to the deprecated ADMIN_SERVICE_TOKEN, which still grants all three scopes,
    so existing production deployments don't break until they migrate to scoped credentials.
    """

    async def dependency(token: str = Security(api_key_header)) -> ServiceAuthContext:
        provided = token or ""
        if not provided:
            raise HTTPException(status_code=403, detail="Invalid or missing service token")

        context = _match_scoped_token(provided, required_scope) or _match_legacy_token(provided, required_scope)
        if context is None:
            raise HTTPException(status_code=403, detail="Invalid or missing service token")

        return context

    return dependency
