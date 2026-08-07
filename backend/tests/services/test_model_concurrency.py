from __future__ import annotations

import uuid

import pytest
from redis.exceptions import RedisError

from app.core.config import settings
from app.services import model_concurrency


class _FakeRedisClient:
    def __init__(self) -> None:
        self.removed: list[tuple[str, str]] = []

    def zrem(self, key: str, token: str) -> None:
        self.removed.append((key, token))


class _FakeRedis:
    client = _FakeRedisClient()

    @classmethod
    def from_url(cls, *_args: object, **_kwargs: object) -> _FakeRedisClient:
        return cls.client


def test_model_slots_acquire_org_before_global_and_release_in_reverse(
    monkeypatch,
) -> None:
    client = _FakeRedisClient()
    _FakeRedis.client = client
    monkeypatch.setattr(model_concurrency, "Redis", _FakeRedis)
    acquired: list[str] = []

    def fake_acquire(_client, key: str, _limit: int, _token: str) -> None:
        acquired.append(key)

    monkeypatch.setattr(model_concurrency, "_acquire", fake_acquire)
    monkeypatch.setattr(model_concurrency, "_acquire_rate", lambda *_args: None)
    org_id = uuid.uuid4()

    with model_concurrency.distributed_model_slot(org_id=org_id, org_limit=5):
        assert acquired == [
            f"dianfan:model-slots:org:{org_id}",
            "dianfan:model-slots:global",
        ]

    assert [key for key, _token in client.removed] == [
        "dianfan:model-slots:global",
        f"dianfan:model-slots:org:{org_id}",
    ]


def test_model_slots_release_partial_acquisition_on_redis_failure(
    monkeypatch,
) -> None:
    client = _FakeRedisClient()
    _FakeRedis.client = client
    monkeypatch.setattr(model_concurrency, "Redis", _FakeRedis)
    acquired: list[str] = []

    def fake_acquire(_client, key: str, _limit: int, _token: str) -> None:
        acquired.append(key)
        if key == "dianfan:model-slots:global":
            raise RedisError("unavailable")

    monkeypatch.setattr(model_concurrency, "_acquire", fake_acquire)
    monkeypatch.setattr(model_concurrency, "_acquire_rate", lambda *_args: None)
    monkeypatch.setattr(settings, "BILLING_ENFORCEMENT_ENABLED", False)
    org_id = uuid.uuid4()

    with model_concurrency.distributed_model_slot(org_id=org_id, org_limit=5):
        pass

    assert acquired == [
        f"dianfan:model-slots:org:{org_id}",
        "dianfan:model-slots:global",
    ]
    assert [key for key, _token in client.removed] == [
        f"dianfan:model-slots:org:{org_id}"
    ]


def test_model_slots_include_channel_between_org_and_global(monkeypatch) -> None:
    client = _FakeRedisClient()
    _FakeRedis.client = client
    monkeypatch.setattr(model_concurrency, "Redis", _FakeRedis)
    acquired: list[str] = []
    monkeypatch.setattr(
        model_concurrency,
        "_acquire",
        lambda _client, key, _limit, _token: acquired.append(key),
    )
    monkeypatch.setattr(model_concurrency, "_acquire_rate", lambda *_args: None)
    org_id = uuid.uuid4()
    channel_id = uuid.uuid4()

    with model_concurrency.distributed_model_slot(
        org_id=org_id,
        org_limit=5,
        channel_id=channel_id,
        channel_limit=7,
    ):
        assert acquired == [
            f"dianfan:model-slots:org:{org_id}",
            f"dianfan:model-slots:channel:{channel_id}",
            "dianfan:model-slots:global",
        ]

    assert [key for key, _token in client.removed] == list(reversed(acquired))


def test_model_slots_fail_closed_in_billing_mode(monkeypatch) -> None:
    monkeypatch.setattr(model_concurrency, "Redis", _FakeRedis)
    monkeypatch.setattr(settings, "BILLING_ENFORCEMENT_ENABLED", True)
    monkeypatch.setattr(
        model_concurrency,
        "_acquire_rate",
        lambda *_args: (_ for _ in ()).throw(RedisError("unavailable")),
    )

    with pytest.raises(model_concurrency.ModelConcurrencyUnavailable):
        with model_concurrency.distributed_model_slot(
            org_id=uuid.uuid4(), org_limit=5
        ):
            pass
