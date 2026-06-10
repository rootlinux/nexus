import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.core.config import settings

api_key_header = APIKeyHeader(name="X-Service-Token", auto_error=False)


async def require_service_token(token: str = Security(api_key_header)) -> str:
    if not settings.ADMIN_SERVICE_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid or missing service token")
    provided = token or ""
    if not provided:
        raise HTTPException(status_code=403, detail="Invalid or missing service token")
    if not secrets.compare_digest(provided, settings.ADMIN_SERVICE_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid or missing service token")

    return token
