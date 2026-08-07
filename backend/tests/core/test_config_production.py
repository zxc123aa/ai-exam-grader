import base64

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def production_settings(**overrides) -> Settings:
    values = {
        "PROJECT_NAME": "点凡阅卷",
        "ENVIRONMENT": "production",
        "FRONTEND_HOST": "https://app.example.com",
        "SECRET_KEY": "s" * 48,
        "POSTGRES_SERVER": "db.example.com",
        "POSTGRES_USER": "app",
        "POSTGRES_PASSWORD": "strong-password",
        "POSTGRES_DB": "dianfan",
        "FIRST_SUPERUSER": "admin@example.com",
        "FIRST_SUPERUSER_PASSWORD": "strong-admin-password",
        "STORAGE_BACKEND": "oss",
        "OSS_ENDPOINT": "https://oss-cn-hangzhou.aliyuncs.com",
        "OSS_BUCKET_NAME": "dianfan-private",
        "OSS_ACCESS_KEY_ID": "key-id",
        "OSS_ACCESS_KEY_SECRET": "key-secret",
        "PROVIDER_CREDENTIAL_MASTER_KEY": base64.b64encode(b"x" * 32).decode(),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_settings_accept_secure_configuration() -> None:
    settings = production_settings()
    assert settings.STORAGE_BACKEND == "oss"


def test_production_settings_reject_local_storage() -> None:
    with pytest.raises(ValidationError, match="STORAGE_BACKEND=oss"):
        production_settings(STORAGE_BACKEND="local")


def test_production_settings_reject_invalid_provider_master_key() -> None:
    with pytest.raises(ValidationError, match="exactly 32 bytes"):
        production_settings(PROVIDER_CREDENTIAL_MASTER_KEY=base64.b64encode(b"short").decode())
