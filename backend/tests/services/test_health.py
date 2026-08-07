from app.services import health
from app.services.health import DependencyStatus


def test_readiness_reports_each_dependency(monkeypatch) -> None:
    monkeypatch.setattr(
        health, "check_database", lambda: DependencyStatus(ok=True)
    )
    monkeypatch.setattr(
        health,
        "check_redis",
        lambda: DependencyStatus(ok=False, detail="RedisError"),
    )
    monkeypatch.setattr(
        health, "check_storage", lambda: DependencyStatus(ok=True)
    )

    ready, dependencies = health.readiness_status()

    assert ready is False
    assert dependencies == {
        "database": {"ok": True, "detail": "ok"},
        "redis": {"ok": False, "detail": "RedisError"},
        "storage": {"ok": True, "detail": "ok"},
    }
