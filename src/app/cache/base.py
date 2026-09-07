"""CacheProvider protocol. local -> InMemoryCache. aws -> RedisCache on ElastiCache.

Namespaces (see DEVELOPMENT_PLAN.md > Caching): ocr:, emb:, graph:, state:, llm:.
"""

from typing import Any, Protocol

from app.core.exceptions import AppError
from app.core.settings import Settings
from app.observability.metrics import cache_operations_total


def record_cache_result(key: str, hit: bool) -> None:
    namespace = key.split(":", 1)[0] if ":" in key else "default"
    cache_operations_total.labels(namespace=namespace, result="hit" if hit else "miss").inc()


class CacheProvider(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...

    def delete(self, key: str) -> None: ...

    def get_or_set(self, key: str, ttl_seconds: int, compute: Any) -> Any:
        """compute is a zero-arg callable invoked only on a miss."""
        ...


def get_cache(settings: Settings) -> "CacheProvider":
    if settings.use_redis:
        from app.cache.redis_cache import RedisCache

        if not settings.redis_url:
            raise AppError("USE_REDIS is true but REDIS_URL is not set")
        return RedisCache(settings.redis_url)

    from app.cache.memory_cache import InMemoryCache

    return InMemoryCache()
