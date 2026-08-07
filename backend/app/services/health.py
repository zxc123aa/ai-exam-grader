from __future__ import annotations

from dataclasses import dataclass

import psycopg
from redis import Redis

from app.core.config import settings
from app.services.object_storage import check_storage_backend


@dataclass(frozen=True)
class DependencyStatus:
    ok: bool
    detail: str = "ok"


def check_database() -> DependencyStatus:
    try:
        with psycopg.connect(
            host=settings.POSTGRES_SERVER,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB,
            connect_timeout=2,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception as exc:
        return DependencyStatus(ok=False, detail=type(exc).__name__)
    return DependencyStatus(ok=True)


def check_redis() -> DependencyStatus:
    try:
        client = Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=1,
            socket_timeout=1,
            retry_on_timeout=False,
        )
        client.ping()
        client.close()
    except Exception as exc:
        return DependencyStatus(ok=False, detail=type(exc).__name__)
    return DependencyStatus(ok=True)


def check_storage() -> DependencyStatus:
    try:
        check_storage_backend()
    except Exception as exc:
        return DependencyStatus(ok=False, detail=type(exc).__name__)
    return DependencyStatus(ok=True)


def readiness_status() -> tuple[bool, dict[str, dict[str, str | bool]]]:
    checks = {
        "database": check_database(),
        "redis": check_redis(),
        "storage": check_storage(),
    }
    payload = {
        name: {"ok": result.ok, "detail": result.detail}
        for name, result in checks.items()
    }
    return all(result.ok for result in checks.values()), payload
