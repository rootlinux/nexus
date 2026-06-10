import secrets

from fastapi import HTTPException, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

service_token_header = APIKeyHeader(name="X-Service-Token", auto_error=False)


async def require_service_token(token: str = service_token_header) -> str:
    if not settings.ADMIN_SERVICE_TOKEN.strip():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_SERVICE_TOKEN is not configured on the server",
        )

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Service-Token header",
        )

    if not secrets.compare_digest(token, settings.ADMIN_SERVICE_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid service token",
        )

    return token
