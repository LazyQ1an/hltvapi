"""
Async HTTP client for HLTV with anti-bot and stealth capabilities.

v5.0: Single request path through FetchPipeline.
All transport selection, block detection, rate limiting, cookie sharing,
and escalation are handled by the pipeline.

Backward compatible: Endpoints continue using get() and get_soup().
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup
from cachetools import TTLCache

from src.antibot import (
    AdaptiveRateLimiter,
    BlockDetector,
    HumanRequestPattern,
)
from src.config import HLTVConfig
from src.core.pipeline import FetchPipeline, FetchRequest
from src.exceptions import BlockedError, HTTPError
from src.parser import _HAS_SELECTOLAX
from src.storage.archive import HTMLArchive
from src.transport.session_pool import SessionPool
from src.utils.cache import CacheBackend, create_cache
from src.utils.logger import get_logger

logger = get_logger("client")


class HLTVClient:
    """Production-grade async HTTP client for HLTV.org with anti-bot.

    All requests flow through FetchPipeline for unified:
    - Transport selection (curl_cffi -> httpx -> Playwright)
    - Session pooling with independent TLS fingerprints
    - Block detection and adaptive recovery
    - Rate limiting with sliding windows
    - Human behavior simulation (burst/rest patterns)
    - Response validation and HTML archiving

    Usage:
        async with HLTVClient(config) as client:
            html = await client.get("https://www.hltv.org/matches")
            soup = await client.get_soup("https://www.hltv.org/results")
    """

    def __init__(
        self,
        config: HLTVConfig | None = None,
        cache: CacheBackend | None = None,
        archive: HTMLArchive | None = None,
        session_pool: SessionPool | None = None,
    ) -> None:
        self.config = config or HLTVConfig()
        self.cache = cache or create_cache(self.config.cache)
        self._archive = archive

        # Core engines (exposed for monitoring/health endpoints)
        self._rate_limiter = AdaptiveRateLimiter(
            min_delay=self.config.rate_limit.min_delay,
            max_delay=self.config.rate_limit.max_delay,
            jitter=self.config.rate_limit.jitter,
            requests_per_hour=self.config.rate_limit.requests_per_hour,
            requests_per_day=self.config.rate_limit.requests_per_day,
        )
        self._block_detector = BlockDetector()
        self._human_pattern = HumanRequestPattern()
        self._session_pool = session_pool or SessionPool(config=self.config)

        # Unified pipeline (sole request execution path)
        self._pipeline = FetchPipeline(
            session_pool=self._session_pool,
            rate_limiter=self._rate_limiter,
            block_detector=self._block_detector,
            human_pattern=self._human_pattern,
            archive=self._archive,
            config=self.config,
        )

        # Memory cache (L1, front of TieredCache)
        self._mem_cache: TTLCache | None = None
        try:
            self._mem_cache = TTLCache(maxsize=200, ttl=60)
        except Exception:
            pass

        # Stats
        self._stats: dict[str, int] = {
            "total_requests": 0,
            "cache_hits": 0,
            "pipeline_calls": 0,
        }

    async def __aenter__(self) -> "HLTVClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close all connections."""
        await self._session_pool.close()
        if self._archive:
            self._archive.close()

    # --- Public API (backward compatible) ---

    async def get(
        self,
        url: str,
        *,
        use_curl: bool = False,
        force_playwright: bool = False,
        cache_ttl: int | None = None,
        cache_key: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Fetch an HLTV page with caching and anti-bot protection.

        All requests go through FetchPipeline which handles:
        transport selection, session pooling, block detection,
        rate limiting, and automatic escalation.

        Args:
            url: Target URL.
            use_curl: Prefer curl_cffi transport.
            force_playwright: Force Playwright browser rendering.
            cache_ttl: Override cache TTL in seconds.
            cache_key: Custom cache key (defaults to URL).

        Returns:
            HTML response text.

        Raises:
            BlockedError: All transports blocked.
            HTTPError: Fatal transport error.
        """
        self._stats["total_requests"] += 1
        ck = cache_key or url

        # 1. Memory cache (L1)
        if self._mem_cache is not None:
            mem_cached = self._mem_cache.get(ck)
            if mem_cached is not None:
                self._stats["cache_hits"] += 1
                return str(mem_cached)

        # 2. Disk cache (L2/L3 via TieredCache)
        cached = self.cache.get(ck)
        if cached is not None:
            self._stats["cache_hits"] += 1
            if self._mem_cache is not None:
                self._mem_cache[ck] = cached
            return str(cached)

        # 3. Execute through FetchPipeline
        self._stats["pipeline_calls"] += 1
        request = FetchRequest(
            url=url,
            cache_ttl=cache_ttl or self.config.cache.ttl,
            cache_key=ck,
            force_playwright=force_playwright,
            prefer_curl=use_curl or self.config.client.curl_impersonate,
        )

        try:
            response = await self._pipeline.execute(request)
            html = response.html
        except BlockedError:
            raise
        except Exception as e:
            raise HTTPError(
                message=f"Pipeline execution failed: {e}",
                url=url,
            ) from e

        # Cache and return
        self._cache_set(ck, html, ttl=cache_ttl)
        return html

    async def get_soup(
        self,
        url: str,
        *,
        parser: str = "html.parser",
        **kwargs: Any,
    ) -> Any:
        """Fetch and parse into a searchable tree object.

        Uses selectolax when available (~3x faster), falls back to BeautifulSoup.

        Args:
            url: Target URL.
            parser: BS4 parser type (ignored when selectolax is used).
            **kwargs: Additional arguments forwarded to get().

        Returns:
            Parsed tree (selectolax HTMLParser or BeautifulSoup).
        """
        html = await self.get(url, **kwargs)
        if _HAS_SELECTOLAX:
            from selectolax.parser import HTMLParser
            return HTMLParser(html)
        return BeautifulSoup(html, parser)

    def _cache_set(self, key: str, value: str, ttl: int | None = None) -> None:
        """Write-through to all cache layers."""
        if self._mem_cache is not None:
            self._mem_cache[key] = value
        self.cache.set(key, value, ttl=ttl)

    def clear_cache(self) -> None:
        """Clear all cache layers."""
        if self._mem_cache is not None:
            self._mem_cache.clear()
        self.cache.clear()
        logger.info("Cache cleared")

    async def _get_curl_session(self) -> Any | None:
        """Get a curl_cffi session for direct transport access (used by demos)."""
        try:
            session = await self._session_pool.acquire("curl")
            return session.client if session else None
        except Exception:
            return None

    def get_client_stats(self) -> dict[str, Any]:
        """Get aggregate client statistics."""
        return {
            **self._stats,
            "pipeline": self._pipeline.get_stats(),
            "rate_limiter": self._rate_limiter.get_stats(),
            "session_pool": self._session_pool.get_stats(),
        }
