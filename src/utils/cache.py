"""
v4.0: Three-tier cache system — L1 (memory) → L2 (LRU TTL) → L3 (diskcache/Redis)

Automatic promotion: L3 hit → promoted to L2 → promoted to L1.
"""

from __future__ import annotations

from typing import Any

try:
    from cachetools import TTLCache
    _HAS_CACHETOOLS = True
except ImportError:
    _HAS_CACHETOOLS = False


class TieredCache:
    """Three-tier cache with automatic promotion.

    L1: In-memory dict (fastest, small, FIFO eviction)
    L2: LRU + TTL memory cache (bounded, time-aware)
    L3: Disk/Redis persistent cache

    Read path: L1 → L2 → L3 → miss
    Write path: L1 + L2 + L3 (write-through)
    """

    def __init__(
        self,
        l1_maxsize: int = 50,
        l2_maxsize: int = 200,
        l2_ttl: int = 60,
        l3_backend: Any | None = None,
    ) -> None:
        self._l1: dict[str, Any] = {}
        self._l1_maxsize = l1_maxsize

        if _HAS_CACHETOOLS:
            self._l2: TTLCache | None = TTLCache(
                maxsize=l2_maxsize, ttl=l2_ttl,
            )
        else:
            self._l2 = None

        self._l3 = l3_backend

        self._hits: dict[str, int] = {
            "l1": 0, "l2": 0, "l3": 0, "miss": 0,
        }

    def get(self, key: str) -> Any | None:
        if key in self._l1:
            self._hits["l1"] += 1
            return self._l1[key]

        if self._l2 is not None and key in self._l2:
            self._hits["l2"] += 1
            val = self._l2[key]
            self._promote_to_l1(key, val)
            return val

        if self._l3 is not None:
            val = self._l3.get(key)
            if val is not None:
                self._hits["l3"] += 1
                self._promote_to_l2(key, val)
                self._promote_to_l1(key, val)
                return val

        self._hits["miss"] += 1
        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._l1[key] = value
        if len(self._l1) > self._l1_maxsize:
            oldest = next(iter(self._l1))
            del self._l1[oldest]

        if self._l2 is not None:
            self._l2[key] = value

        if self._l3 is not None:
            try:
                self._l3.set(key, value, ttl=ttl)
            except TypeError:
                expire = ttl if ttl else None
                self._l3.set(key, value, expire=expire)

    def _promote_to_l1(self, key: str, value: Any) -> None:
        self._l1[key] = value
        if len(self._l1) > self._l1_maxsize:
            oldest = next(iter(self._l1))
            del self._l1[oldest]

    def _promote_to_l2(self, key: str, value: Any) -> None:
        if self._l2 is not None:
            self._l2[key] = value

    def clear(self) -> None:
        self._l1.clear()
        if self._l2 is not None:
            self._l2.clear()
        if self._l3 is not None:
            self._l3.clear()
        self._hits = {"l1": 0, "l2": 0, "l3": 0, "miss": 0}

    def get_stats(self) -> dict[str, int | float]:
        total = sum(self._hits.values()) or 1
        return {
            **self._hits,
            "l1_size": len(self._l1),
            "l2_size": len(self._l2) if self._l2 else 0,
            "hit_ratio": round(
                (total - self._hits["miss"]) / total * 100, 1,
            ),
        }


# Backward-compatible aliases for importers
CacheBackend = TieredCache


def create_cache(config: Any) -> TieredCache:
    """Create a cache backend from config.

    Args:
        config: CacheConfig instance with backend, ttl, diskcache_dir, redis_url.

    Returns:
        TieredCache with appropriate L3 backend.
    """
    backend = getattr(config, "backend", "diskcache")
    l3_backend: Any = None

    if backend == "diskcache":
        try:
            import diskcache
            cache_dir = getattr(config, "diskcache_dir", ".cache/hltv")
            l3_backend = diskcache.Cache(cache_dir)
        except ImportError:
            pass
    elif backend == "redis":
        try:
            import redis as redis_mod
            redis_url = getattr(config, "redis_url", "redis://localhost:6379/0")
            l3_backend = redis_mod.from_url(redis_url)
        except ImportError:
            pass
    elif backend == "none":
        l3_backend = None

    return TieredCache(l3_backend=l3_backend)
