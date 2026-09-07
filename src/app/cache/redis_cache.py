"""aws: ElastiCache Redis. `redis` is imported lazily inside __init__, never at module
import time — so a local run works even without the `redis` package installed.
"""

import json
from collections.abc import Callable
from typing import Any

from app.cache.base import record_cache_result


class RedisCache:
    def __init__(self, redis_url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(redis_url)

    def get(self, key: str) -> Any | None:
        raw = self._client.get(key)
        record_cache_result(key, hit=raw is not None)
        return json.loads(raw) if raw is not None else None

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._client.set(key, json.dumps(value), ex=ttl_seconds)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def get_or_set(self, key: str, ttl_seconds: int, compute: Callable[[], Any]) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = compute()
        self.set(key, value, ttl_seconds)
        return value
