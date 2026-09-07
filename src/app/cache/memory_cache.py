"""local: dict with expiry timestamps. Same interface as RedisCache — never imports `redis`."""

import time
from collections.abc import Callable
from typing import Any

from app.cache.base import record_cache_result


class InMemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            record_cache_result(key, hit=False)
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            del self._store[key]
            record_cache_result(key, hit=False)
            return None
        record_cache_result(key, hit=True)
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._store[key] = (time.monotonic() + ttl_seconds, value)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def get_or_set(self, key: str, ttl_seconds: int, compute: Callable[[], Any]) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = compute()
        self.set(key, value, ttl_seconds)
        return value
