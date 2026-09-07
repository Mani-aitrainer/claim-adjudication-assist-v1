import time

from app.cache.base import get_cache
from app.cache.memory_cache import InMemoryCache
from app.core.settings import Settings


def test_get_and_set_roundtrip() -> None:
    cache = InMemoryCache()
    cache.set("k", {"v": 1}, ttl_seconds=60)
    assert cache.get("k") == {"v": 1}


def test_get_missing_key_returns_none() -> None:
    assert InMemoryCache().get("missing") is None


def test_expired_entry_returns_none() -> None:
    cache = InMemoryCache()
    cache.set("k", "v", ttl_seconds=0)
    time.sleep(0.01)
    assert cache.get("k") is None


def test_delete_removes_entry() -> None:
    cache = InMemoryCache()
    cache.set("k", "v", ttl_seconds=60)
    cache.delete("k")
    assert cache.get("k") is None


def test_get_or_set_only_computes_once_on_hit() -> None:
    cache = InMemoryCache()
    calls = []

    def compute() -> str:
        calls.append(1)
        return "computed"

    first = cache.get_or_set("k", 60, compute)
    second = cache.get_or_set("k", 60, compute)
    assert first == second == "computed"
    assert len(calls) == 1


def test_get_cache_returns_in_memory_cache_when_redis_disabled() -> None:
    settings = Settings(use_redis=False)
    assert isinstance(get_cache(settings), InMemoryCache)
