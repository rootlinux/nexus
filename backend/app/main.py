import logging
import os
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.http import HostValidationMiddleware, TrustedProxyHeadersMiddleware, apply_cache_control_headers
from app.core.rate_limit import get_redis_client
from app.api import api_router
from app.bootstrap import bootstrap_admin_if_configured
from app.services.mail import get_mail_sender
from app.storage import get_storage_provider
from app.storage.local import LocalStorageProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("app.startup")

app = FastAPI(
    title="Nexus API",
    description="Social platform API",
    version="0.1.0",
    debug=settings.DEBUG,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    TrustedProxyHeadersMiddleware,
    trusted_proxy_cidrs=settings.TRUSTED_PROXY_CIDRS,
    enabled=settings.TRUST_PROXY_HEADERS,
)

if settings.ALLOWED_HOSTS:
    app.add_middleware(HostValidationMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

default_cors_allow_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:19006",
    "http://127.0.0.1:19006",
]
cors_allow_origins = settings.CORS_ALLOWED_ORIGINS or (
    default_cors_allow_origins if settings.APP_ENV == "development" else []
)

# CORS middleware - only allow explicitly configured frontends to send authenticated requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id", "X-Session-Transport", "X-Skip-Auth-Refresh", "X-Signup-Request-Key", "X-Service-Token"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        "script-src 'self'; "
        # unsafe-inline required: frontend uses inline styles extensively across all React components.
        # This is an accepted risk — removing it would break rendering without a full refactor.
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "img-src 'self'; "
        "media-src 'self'; "
        "font-src 'self' data:; "
        "frame-ancestors 'none'"
    )
    apply_cache_control_headers(
        response,
        path=request.url.path,
        uploads_prefix=settings.LOCAL_UPLOAD_URL_PREFIX,
        uploads_cache_control=settings.UPLOADS_CACHE_CONTROL,
    )
    return response


@app.get("/")
async def root():
    return {"message": "Nexus API", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "ok", "checks": {"app": "alive"}}


async def _dependency_readiness() -> tuple[bool, dict[str, str]]:
    checks: dict[str, str] = {}
    ready = True

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        ready = False
        checks["database"] = "error"
        logger.warning("Readiness database check failed", extra={"dependency": "database"}, exc_info=True)

    try:
        redis_client = await get_redis_client()
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        ready = False
        checks["redis"] = "error"
        logger.warning("Readiness redis check failed", extra={"dependency": "redis"}, exc_info=True)

    return ready, checks


@app.get("/ready")
async def readiness_check():
    ready, checks = await _dependency_readiness()
    payload = {"status": "ready" if ready else "not_ready", "checks": checks}
    if ready:
        return payload
    return JSONResponse(status_code=503, content=payload)


@app.on_event("startup")
async def log_startup_configuration() -> None:
    try:
        get_mail_sender()
    except RuntimeError as exc:
        logger.error("Mail configuration error: %s", exc)
        raise

    if settings.is_production:
        if not settings.CORS_ALLOWED_ORIGINS:
            raise RuntimeError(
                "CORS_ALLOWED_ORIGINS must be set in production. "
                "Refusing to start with an empty CORS allowlist."
            )
        if not cors_allow_origins:
            logger.warning(
                "CORS_ALLOWED_ORIGINS is empty in production — all cross-origin requests will be blocked."
            )
    logger.info(
        "Application startup complete",
        extra={
            "app_env": settings.APP_ENV,
            "debug": settings.DEBUG,
            "cors_origins": len(settings.CORS_ALLOWED_ORIGINS),
            "allowed_hosts": len(settings.ALLOWED_HOSTS),
            "trust_proxy_headers": settings.TRUST_PROXY_HEADERS,
            "storage_provider": settings.STORAGE_PROVIDER,
        },
    )
    await bootstrap_admin_if_configured()


app.include_router(api_router, prefix="/api")

LEGACY_FEEDBACK_UPLOADS_PREFIX = f"{settings.LOCAL_UPLOAD_URL_PREFIX.rstrip('/')}/feedback"


@app.api_route(f"{LEGACY_FEEDBACK_UPLOADS_PREFIX}/{{path:path}}", methods=["GET", "HEAD"], include_in_schema=False)
async def block_legacy_feedback_uploads(path: str):
    response = JSONResponse(status_code=404, content={"detail": "Not found"})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


# Serve uploaded files for local storage
storage_provider = get_storage_provider()
if isinstance(storage_provider, LocalStorageProvider):
    upload_dir = storage_provider.get_static_mount_directory()
    os.makedirs(upload_dir, exist_ok=True)
    app.mount(settings.LOCAL_UPLOAD_URL_PREFIX, StaticFiles(directory=upload_dir), name="uploads")
