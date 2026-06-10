import logging
import re
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource, EnvSettingsSource

_config_logger = logging.getLogger(__name__)


CSV_ENV_FIELDS = {"CORS_ALLOWED_ORIGINS", "ALLOWED_HOSTS", "TRUSTED_PROXY_CIDRS"}
KNOWN_WEAK_SECRET_MARKERS = (
    "changeme",
    "change-in-production",
    "dev-secret",
    "test-secret",
    "generate-a-long-random-secret",
    "replace-with-",
    "placeholder",
    "example-secret",
    "shared-secret",
    "local-dev-secret",
    "local-smoke-secret",
)
KNOWN_WEAK_SECRET_VALUES = {
    "",
    "secret",
    "default",
    "defaultsecret",
    "sharedsecret",
    "replace-with-a-local-dev-secret-before-running",
    "replace-with-a-strong-64-plus-character-secret",
    "0123456789abcdef" * 4,
}


def _looks_like_repeated_secret_pattern(secret: str) -> bool:
    for chunk_size in (4, 8, 16, 32):
        if len(secret) % chunk_size != 0 or len(secret) // chunk_size < 4:
            continue
        chunk = secret[:chunk_size]
        if chunk * (len(secret) // chunk_size) == secret:
            return True
    return False


class CsvEnvSettingsSource(EnvSettingsSource):
    def __call__(self) -> dict[str, Any]:
        data = super().__call__()
        data.pop("ALGORITHM", None)
        return data

    def prepare_field_value(self, field_name: str, field, value, value_is_complex: bool):
        if field_name in CSV_ENV_FIELDS and isinstance(value, str):
            return value
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class CsvDotEnvSettingsSource(DotEnvSettingsSource):
    def __call__(self) -> dict[str, Any]:
        data = super().__call__()
        data.pop("ALGORITHM", None)
        return data

    def prepare_field_value(self, field_name: str, field, value, value_is_complex: bool):
        if field_name in CSV_ENV_FIELDS and isinstance(value, str):
            return value
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    
    # Redis
    REDIS_URL: str
    
    # Auth
    SECRET_KEY: str
    ALGORITHM: Literal["HS256"] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    REFRESH_COOKIE_NAME: str = "x_refresh_token"
    REFRESH_COOKIE_SAMESITE: str = "lax"
    REFRESH_COOKIE_SECURE: Optional[bool] = None
    REFRESH_COOKIE_DOMAIN: Optional[str] = None
    WEB_BASE_URL: str = "http://localhost:3000"
    EMAIL_VERIFICATION_TOKEN_TTL_MINUTES: int = 30
    PASSWORD_RESET_TOKEN_TTL_MINUTES: int = 30
    ENABLE_BOOTSTRAP_ADMIN: bool = False
    BOOTSTRAP_ADMIN_USERNAME: Optional[str] = None
    BOOTSTRAP_ADMIN_EMAIL: Optional[str] = None
    BOOTSTRAP_ADMIN_PASSWORD: Optional[str] = None
    BOOTSTRAP_ADMIN_DISPLAY_NAME: Optional[str] = None
    ENABLE_ADMIN_WEBAUTHN_RECOVERY: bool = False
    ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER: Optional[str] = None
    ADMIN_WEBAUTHN_RECOVERY_TOKEN_TTL_MINUTES: int = 10
    ADMIN_SERVICE_TOKEN: str = ""

    # App
    APP_ENV: str = "development"
    DEBUG: bool = False
    CORS_ALLOWED_ORIGINS: list[str] = []
    ALLOWED_HOSTS: list[str] = []
    TRUSTED_PROXY_CIDRS: list[str] = []
    TRUST_PROXY_HEADERS: bool = False
    UPLOADS_CACHE_CONTROL: str = "public, max-age=3600"
    
    # WebAuthn / FIDO2
    WEBAUTHN_RP_ID: str = "localhost"
    WEBAUTHN_RP_NAME: str = "Nexus"
    WEBAUTHN_ORIGIN: str = "http://localhost:3000"
    WEBAUTHN_MFA_TOKEN_TTL_MINUTES: int = 5

    # Invite
    INVITE_CODE_LENGTH: int = 32

    # Storage
    STORAGE_PROVIDER: str = "local"
    LOCAL_UPLOAD_DIR: str = "uploads"
    LOCAL_UPLOAD_URL_PREFIX: str = "/uploads"
    S3_BUCKET_NAME: Optional[str] = None
    S3_REGION: Optional[str] = None
    S3_ENDPOINT_URL: Optional[str] = None
    S3_PUBLIC_BASE_URL: Optional[str] = None
    S3_ACCESS_KEY_ID: Optional[str] = None
    S3_SECRET_ACCESS_KEY: Optional[str] = None

    # Mail
    MAIL_PROVIDER: str = "capture"
    MAIL_CAPTURE_DIR: str = "tmp/mail"
    MAIL_FROM_EMAIL: str = "no-reply@nexus.local"
    MAIL_FROM_NAME: str = "Nexus"
    RESEND_API_KEY: str = ""
    FEEDBACK_REPORT_TO_EMAIL: str = "beta@linusx.xyz"
    FEEDBACK_ATTACHMENT_MAX_BYTES: int = 5 * 1024 * 1024
    FEEDBACK_ATTACHMENT_STORAGE_SUBDIR: str = "feedback"
    FEEDBACK_ATTACHMENT_LOCAL_DIR: str = "feedback_private_uploads"
    FEEDBACK_ATTACHMENT_URL_PREFIX: str = "/api/feedback/attachments"
    FEEDBACK_ATTACHMENT_URL_TTL_MINUTES: int = 60 * 24 * 14
    FEEDBACK_ATTACHMENT_RETENTION_DAYS: int = 30
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = ""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        str_to_bool=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            CsvEnvSettingsSource(settings_cls),
            CsvDotEnvSettingsSource(settings_cls),
            file_secret_settings,
        )

    @field_validator("DEBUG", mode="before")
    @classmethod
    def normalize_debug_value(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"debug", "dev", "development"}:
                return True
        return value

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def normalize_cors_origins(cls, value: object) -> object:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("ALLOWED_HOSTS", "TRUSTED_PROXY_CIDRS", mode="before")
    @classmethod
    def normalize_csv_list(cls, value: object) -> object:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("REFRESH_COOKIE_SAMESITE", mode="before")
    @classmethod
    def normalize_cookie_samesite(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("REFRESH_COOKIE_SECURE", mode="before")
    @classmethod
    def normalize_refresh_cookie_secure(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value in {0, 1}:
                return bool(value)
            raise ValueError("REFRESH_COOKIE_SECURE must be a boolean value")
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "":
                return None
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
            raise ValueError("REFRESH_COOKIE_SECURE must be a boolean value")
        return value

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        app_env = self.normalized_app_env
        is_production = self.is_production
        predictable_bootstrap_usernames = {
            "admin",
            "administrator",
            "root",
            "superuser",
            "testadmin",
            "demoadmin",
        }
        predictable_bootstrap_emails = {
            "admin@example.com",
            "admin@localtest.me",
            "test@example.com",
            "demo@example.com",
        }

        if self.ALGORITHM != "HS256":
            raise ValueError("ALGORITHM must be fixed to HS256")

        if self.REFRESH_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
            raise ValueError("REFRESH_COOKIE_SAMESITE must be one of: lax, strict, none")

        if app_env in {"staging", "stage"} and self.DEBUG:
            raise ValueError("DEBUG cannot be enabled in staging")

        if self.ENABLE_BOOTSTRAP_ADMIN:
            if app_env not in {"development", "dev", "local", "test", "testing"}:
                raise ValueError("ENABLE_BOOTSTRAP_ADMIN is only allowed in local/dev/test environments")

            if not self.BOOTSTRAP_ADMIN_USERNAME or not self.BOOTSTRAP_ADMIN_EMAIL or not self.BOOTSTRAP_ADMIN_PASSWORD:
                raise ValueError(
                    "BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_EMAIL, and BOOTSTRAP_ADMIN_PASSWORD are required when ENABLE_BOOTSTRAP_ADMIN is true"
                )

            username = self.BOOTSTRAP_ADMIN_USERNAME.strip().lower()
            email = self.BOOTSTRAP_ADMIN_EMAIL.strip().lower()
            password = self.BOOTSTRAP_ADMIN_PASSWORD

            if username in predictable_bootstrap_usernames:
                raise ValueError("BOOTSTRAP_ADMIN_USERNAME must not use a predictable default identifier")
            if email in predictable_bootstrap_emails:
                raise ValueError("BOOTSTRAP_ADMIN_EMAIL must not use a predictable default identifier")
            if "@" not in email:
                raise ValueError("BOOTSTRAP_ADMIN_EMAIL must be a valid email address")
            if len(password) < 16:
                raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must be at least 16 characters")
            try:
                from zxcvbn import zxcvbn as _zxcvbn  # noqa: PLC0415
                result = _zxcvbn(password, user_inputs=[username, email])
                if result["score"] < 3:
                    feedback = " ".join(result["feedback"]["suggestions"]).strip()
                    hint = f" ({feedback})" if feedback else ""
                    raise ValueError(
                        f"BOOTSTRAP_ADMIN_PASSWORD is too weak (zxcvbn score {result['score']}/4, need ≥3){hint}"
                    )
            except ImportError:
                raise ValueError(
                    "zxcvbn package is required for bootstrap admin password validation. "
                    "Run: pip install zxcvbn"
                )

        if self.ENABLE_ADMIN_WEBAUTHN_RECOVERY:
            if app_env not in {"staging", "stage", "test", "testing"}:
                raise ValueError(
                    "ENABLE_ADMIN_WEBAUTHN_RECOVERY is only allowed in staging/test environments"
                )
            if not self.ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER or not self.ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER.strip():
                raise ValueError(
                    "ADMIN_WEBAUTHN_RECOVERY_IDENTIFIER is required when ENABLE_ADMIN_WEBAUTHN_RECOVERY is true"
                )
            if not 1 <= self.ADMIN_WEBAUTHN_RECOVERY_TOKEN_TTL_MINUTES <= 30:
                raise ValueError("ADMIN_WEBAUTHN_RECOVERY_TOKEN_TTL_MINUTES must be between 1 and 30")

        if not is_production:
            return self

        secret_key = self.SECRET_KEY.strip()
        if not secret_key:
            raise ValueError("SECRET_KEY must not be empty in production")
        if len(secret_key) < 64:
            raise ValueError("SECRET_KEY must be at least 64 characters in production")
        secret_key_normalized = secret_key.lower()
        if secret_key_normalized in KNOWN_WEAK_SECRET_VALUES:
            raise ValueError("SECRET_KEY must not use a known default or shared example value in production")
        if any(marker in secret_key_normalized for marker in KNOWN_WEAK_SECRET_MARKERS):
            raise ValueError("SECRET_KEY must be a strong non-placeholder value in production")
        if _looks_like_repeated_secret_pattern(secret_key_normalized):
            raise ValueError("SECRET_KEY must not use a repeated or template-like pattern in production")
        if secret_key == secret_key.lower() and secret_key.replace("-", "").replace("_", "").isalpha():
            raise ValueError("SECRET_KEY appears to be a human-readable string; use a random value in production")

        if self.DEBUG:
            raise ValueError("DEBUG cannot be enabled in production")

        if not self.ALLOWED_HOSTS:
            raise ValueError("ALLOWED_HOSTS must be set in production")

        invalid_hosts = {
            host for host in self.ALLOWED_HOSTS if host in {"*", "localhost", "127.0.0.1", "0.0.0.0"}
        }
        if invalid_hosts:
            raise ValueError("ALLOWED_HOSTS cannot contain wildcard or localhost-style entries in production")

        invalid_origins = [
            origin
            for origin in self.CORS_ALLOWED_ORIGINS
            if "localhost" in origin.lower() or "127.0.0.1" in origin or origin.strip() == "*"
        ]
        if invalid_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS cannot contain wildcard or localhost origins in production")

        if self.TRUST_PROXY_HEADERS and not self.TRUSTED_PROXY_CIDRS:
            raise ValueError("TRUSTED_PROXY_CIDRS must be set when TRUST_PROXY_HEADERS is enabled")

        if self.REFRESH_COOKIE_SECURE is False:
            raise ValueError("REFRESH_COOKIE_SECURE cannot be disabled in production")

        provider = self.MAIL_PROVIDER.strip().lower()

        if provider == "resend" and not self.RESEND_API_KEY.strip():
            raise ValueError("RESEND_API_KEY must be set when MAIL_PROVIDER=resend")

        if provider != "capture":
            mail_from_email = self.MAIL_FROM_EMAIL.strip()
            mail_from_name = self.MAIL_FROM_NAME.strip()
            if not mail_from_email:
                raise ValueError("MAIL_FROM_EMAIL must be set when using a real mail provider")
            if not mail_from_name:
                raise ValueError("MAIL_FROM_NAME must be set when using a real mail provider")
            if "@" not in mail_from_email:
                raise ValueError("MAIL_FROM_EMAIL must be a valid email address when using a real mail provider")
            mail_from_domain = mail_from_email.rsplit("@", 1)[-1].lower()
            if mail_from_domain in {"localhost", "localtest.me"} or mail_from_domain.endswith(".local"):
                raise ValueError("MAIL_FROM_EMAIL must use a real domain when using a real mail provider")

            parsed_web_base_url = urlparse(self.WEB_BASE_URL.strip())
            web_base_host = parsed_web_base_url.hostname.lower() if parsed_web_base_url.hostname else ""
            if (
                parsed_web_base_url.scheme != "https"
                or not web_base_host
                or web_base_host in {"localhost", "127.0.0.1", "0.0.0.0", "localtest.me"}
                or web_base_host.endswith(".local")
                or web_base_host.endswith(".localtest.me")
            ):
                raise ValueError("WEB_BASE_URL must be an https production URL when using a real mail provider")

        if (
            self.REDIS_URL.startswith("redis://")
            and not re.search(r":([^@]+)@", self.REDIS_URL)
        ):
            _config_logger.warning(
                "Redis is running without authentication or TLS in production. "
                "Consider using rediss:// with a password."
            )

        return self

    @property
    def web_push_enabled(self) -> bool:
        return bool(self.VAPID_PUBLIC_KEY.strip() and self.VAPID_PRIVATE_KEY.strip() and self.VAPID_SUBJECT.strip())

    @property
    def refresh_cookie_secure(self) -> bool:
        if self.REFRESH_COOKIE_SECURE is not None:
            return self.REFRESH_COOKIE_SECURE
        if self.ALLOWED_HOSTS and all(host.endswith(".localtest.me") for host in self.ALLOWED_HOSTS):
            return False
        return self.normalized_app_env not in {"development", "dev", "local"}

    @property
    def normalized_app_env(self) -> str:
        return self.APP_ENV.strip().lower()

    @property
    def is_production(self) -> bool:
        return self.normalized_app_env in {"production", "prod", "release"}

settings = Settings()
