from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings

_ACQUIRE = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[2]) then
  redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
  return 1
end
return 0
"""

_ACQUIRE_RATE = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1] - 60)
if redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[2]) then
  redis.call('ZADD', KEYS[1], ARGV[1], ARGV[3])
  redis.call('EXPIRE', KEYS[1], 61)
  return 1
end
return 0
"""


class ModelConcurrencyUnavailable(RuntimeError):
    pass


def _acquire(client: Redis, key: str, limit: int, token: str) -> None:
    ttl_seconds = max(600, settings.VISION_TIMEOUT_SECONDS * 3)
    while True:
        now = time.time()
        accepted = client.eval(
            _ACQUIRE,
            1,
            key,
            now,
            max(1, limit),
            now + ttl_seconds,
            token,
            ttl_seconds,
        )
        if accepted:
            return
        time.sleep(0.05)


def _acquire_rate(client: Redis, key: str, limit: int, token: str) -> None:
    while True:
        accepted = client.eval(_ACQUIRE_RATE, 1, key, time.time(), max(1, limit), token)
        if accepted:
            return
        time.sleep(0.1)


@contextmanager
def distributed_model_slot(
    *,
    org_id: uuid.UUID,
    org_limit: int,
    global_limit: int = 32,
    channel_id: uuid.UUID | None = None,
    channel_limit: int | None = None,
    calls_per_minute: int = 120,
) -> Iterator[None]:
    client = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=1,
        retry_on_timeout=False,
    )
    token = str(uuid.uuid4())
    global_key = "dianfan:model-slots:global"
    org_key = f"dianfan:model-slots:org:{org_id}"
    channel_key = f"dianfan:model-slots:channel:{channel_id}" if channel_id else None
    rate_key = f"dianfan:model-rate:org:{org_id}"
    acquired: list[str] = []
    try:
        _acquire_rate(client, rate_key, calls_per_minute, token)
        _acquire(client, org_key, org_limit, token)
        acquired.append(org_key)
        if channel_key and channel_limit is not None:
            _acquire(client, channel_key, channel_limit, token)
            acquired.append(channel_key)
        _acquire(client, global_key, global_limit, token)
        acquired.append(global_key)
    except RedisError:
        if settings.BILLING_ENFORCEMENT_ENABLED:
            raise ModelConcurrencyUnavailable("模型调用保护服务暂时不可用")
        # 本地演示环境允许绕过，生产计费开启后必须故障关闭。
        yield
    else:
        yield
    finally:
        for key in reversed(acquired):
            try:
                client.zrem(key, token)
            except RedisError:
                pass
