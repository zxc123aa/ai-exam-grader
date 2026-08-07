import secrets
import warnings
from base64 import b64decode
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            ROOT_DIR / "参考算法" / "2_试卷分析文件" / ".env",
            ROOT_DIR / ".env",
        ),
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""
    REDIS_URL: str = "redis://redis:6379/0"
    PUBLIC_SIGNUP_ENABLED: bool = False
    TURNSTILE_SECRET_KEY: str = ""
    PUBLIC_SIGNUP_TRIAL_RATE_VERSION: str = "2026-demo-v1"
    PUBLIC_SIGNUP_TOKEN_EXPIRE_MINUTES: int = 30
    PUBLIC_SIGNUP_TRIAL_DAYS: int = 30
    PUBLIC_SIGNUP_TRIAL_ANSWER_QUOTA: int = 200
    STORAGE_BACKEND: Literal["local", "oss"] = "local"
    LOCAL_UPLOAD_DIR: Path = ROOT_DIR / "data" / "uploads"
    STORAGE_CACHE_DIR: Path = ROOT_DIR / "data" / "storage-cache"
    OSS_ENDPOINT: str = ""
    OSS_BUCKET_NAME: str = ""
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_PREFIX: str = "dianfan"
    WECHAT_PAY_MCH_ID: str = ""
    WECHAT_PAY_APP_ID: str = ""
    WECHAT_PAY_CERT_SERIAL_NO: str = ""
    WECHAT_PAY_PRIVATE_KEY_PEM: str = ""
    WECHAT_PAY_PLATFORM_CERT_PEM: str = ""
    WECHAT_PAY_API_V3_KEY: str = ""
    WECHAT_PAY_NOTIFY_URL: str = ""
    OCR_ENGINE: Literal["disabled", "tesseract", "paddle_http"] = "disabled"
    OCR_TESSERACT_COMMAND: str = "tesseract"
    OCR_HTTP_URL: str = "http://ocr-service:8010/ocr"
    OCR_HTTP_TIMEOUT_SECONDS: int = 60
    SCAN_ENGINE: Literal[
        "opencv_v1",
        "scan_http",
        "hybrid_v2",
        "exam_scan_rectifier_v1",
        "scan_stable_v1",
    ] = "scan_stable_v1"
    # Local development runs the GPU vision service on the host. Docker Compose
    # overrides this with http://ocr-service:8010/preprocess.
    SCAN_HTTP_URL: str = "http://localhost:8010/preprocess"
    SCAN_HTTP_TIMEOUT_SECONDS: int = 120
    VISION_DEFAULT_PROVIDER: str = "pomoai"
    VISION_DEFAULT_MODEL: str = "gemini-3.5-flash"
    GRADING_DEFAULT_PROVIDER: str = "pomoai"
    GRADING_DEFAULT_MODEL: str = "gpt-5.6-sol"
    VISION_FALLBACK_MODELS: str = "gemini-3.6-flash,gemini-3.5-flash"
    REASONING_FALLBACK_MODELS: str = "gpt-5.6-terra,kimi-k2.7-code,kimi-k3"
    VISION_TIMEOUT_SECONDS: int = 180
    MODEL_MAX_OUTPUT_TOKENS: int = 8192
    REFERENCE_ALGORITHM_URL: str = "http://localhost:3417"
    VISION_MAX_CONCURRENCY: int = 4
    # Production is fail-closed. Local development can explicitly disable this
    # until demo organizations have contracts and answer quotas seeded.
    BILLING_ENFORCEMENT_ENABLED: bool = True
    # Internal Token cost budgets are a platform risk-control layer, not the
    # customer billing unit. Keep disabled until platform budgets are funded.
    TOKEN_BUDGET_ENFORCEMENT_ENABLED: bool = False
    DYNAMIC_PROVIDER_ROUTING_ENABLED: bool = True
    # Base64 encoded 32-byte AES key. Keep it in the server environment or KMS.
    PROVIDER_CREDENTIAL_MASTER_KEY: str = ""
    # Exact hostnames or CIDRs allowed for private relay endpoints.
    PROVIDER_PRIVATE_ENDPOINT_ALLOWLIST: str = ""
    PROVIDER_POMOAI_BASE_URL: str = "https://www.pomoai.ai"
    PROVIDER_POMOAI_API_KEY: str = ""
    PROVIDER_FLUXNODE_GEMINI_BASE_URL: str = "https://fluxnode.org"
    PROVIDER_FLUXNODE_GEMINI_API_KEY: str = ""
    PROVIDER_FLUXNODE_GROK_BASE_URL: str = "https://fluxnode.org"
    PROVIDER_FLUXNODE_GROK_API_KEY: str = ""
    PROVIDER_KIMI_BASE_URL: str = "https://api.kimi.com/coding/v1"
    PROVIDER_KIMI_API_KEY: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        if self.ENVIRONMENT != "local" and self.PUBLIC_SIGNUP_ENABLED:
            if not self.TURNSTILE_SECRET_KEY:
                raise ValueError(
                    "TURNSTILE_SECRET_KEY is required when public signup is enabled"
                )
            if not self.emails_enabled:
                raise ValueError(
                    "SMTP and sender email are required when public signup is enabled"
                )

        if self.ENVIRONMENT == "production":
            if len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if not str(self.FRONTEND_HOST).startswith("https://"):
                raise ValueError("FRONTEND_HOST must use HTTPS in production")
            if self.STORAGE_BACKEND != "oss":
                raise ValueError("Production deployments must use STORAGE_BACKEND=oss")
            oss_values = {
                "OSS_ENDPOINT": self.OSS_ENDPOINT,
                "OSS_BUCKET_NAME": self.OSS_BUCKET_NAME,
                "OSS_ACCESS_KEY_ID": self.OSS_ACCESS_KEY_ID,
                "OSS_ACCESS_KEY_SECRET": self.OSS_ACCESS_KEY_SECRET,
            }
            missing = [name for name, value in oss_values.items() if not value]
            if missing:
                raise ValueError(
                    "Missing production object storage settings: " + ", ".join(missing)
                )
            if self.DYNAMIC_PROVIDER_ROUTING_ENABLED:
                try:
                    master_key = b64decode(
                        self.PROVIDER_CREDENTIAL_MASTER_KEY, validate=True
                    )
                except ValueError as exc:
                    raise ValueError(
                        "PROVIDER_CREDENTIAL_MASTER_KEY must be valid base64"
                    ) from exc
                if len(master_key) != 32:
                    raise ValueError(
                        "PROVIDER_CREDENTIAL_MASTER_KEY must encode exactly 32 bytes"
                    )
            wechat_values = (
                self.WECHAT_PAY_MCH_ID,
                self.WECHAT_PAY_APP_ID,
                self.WECHAT_PAY_CERT_SERIAL_NO,
                self.WECHAT_PAY_PRIVATE_KEY_PEM,
                self.WECHAT_PAY_PLATFORM_CERT_PEM,
                self.WECHAT_PAY_API_V3_KEY,
                self.WECHAT_PAY_NOTIFY_URL,
            )
            if any(wechat_values) and not all(wechat_values):
                raise ValueError(
                    "WeChat Pay configuration must be complete when enabled"
                )
            if self.WECHAT_PAY_NOTIFY_URL and not self.WECHAT_PAY_NOTIFY_URL.startswith(
                "https://"
            ):
                raise ValueError("WECHAT_PAY_NOTIFY_URL must use HTTPS")

        return self


settings = Settings()  # type: ignore
