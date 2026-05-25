"""
Async HTTP client for HLTV with anti-bot and stealth capabilities.

Refactored for v5.0:
- SessionPool 管理多 session 轮换
- FetchPipeline 统一请求生命周期
- AdaptiveRateLimiter 滑动窗口智能调速
- BlockDetector 多层检测
- HumanRequestPattern 模拟真人行为
- HTMLArchive raw HTML 归档

保持向后兼容：endpoints 代码继续使用 get() 和 get_soup() 方法。
"""

from __future__ import annotations

import asyncio
import time as tmod
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from cachetools import TTLCache

from src.antibot import (
    AdaptiveRateLimiter,
    BlockDetector,
    HumanRequestPattern,
    random_profile,
    random_referer,
    random_accept_language,
)
from src.config import HLTVConfig
from src.core.pipeline import FetchPipeline, FetchRequest
from src.exceptions import (
    BlockedError,
    HTTPError,
    RateLimitError,
)
from src.parser import _HAS_SELECTOLAX
from src.storage.archive import HTMLArchive
from src.transport.session_pool import SessionPool
from src.utils.cache import CacheBackend, create_cache
from src.utils.logger import get_logger

logger = get_logger("client")


class HLTVClient:
    """Production-grade async HTTP client for HLTV.org with anti-bot.

    与旧版的区别：
    - 内部使用 SessionPool 管理多个独立 session
    - 使用 FetchPipeline 处理完整的请求生命周期
    - 使用 AdaptiveRateLimiter 滑动窗口调速
    - 使用 BlockDetector 多层检测
    - 集成 HTMLArchive 自动归档
    - 向后兼容：get() 和 get_soup() 方法签名不变

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

        # 核心引擎
        self._rate_limiter = AdaptiveRateLimiter(
            min_delay=self.config.rate_limit.min_delay,
            max_delay=self.config.rate_limit.max_delay,
            jitter=self.config.rate_limit.jitter,
            requests_per_hour=self.config.rate_limit.requests_per_hour,
            requests_per_day=self.config.rate_limit.requests_per_day,
        )
        self._block_detector = BlockDetector()
        self._human_pattern = HumanRequestPattern()
        self._session_pool = session_pool or SessionPool(
            config=self.config,
        )

        # FetchPipeline
        self._pipeline = FetchPipeline(
            session_pool=self._session_pool,
            rate_limiter=self._rate_limiter,
            block_detector=self._block_detector,
            human_pattern=self._human_pattern,
            archive=self._archive,
            config=self.config,
        )

        # 内存缓存
        self._mem_cache: TTLCache | None = None
        try:
            self._mem_cache = TTLCache(maxsize=200, ttl=60)
        except ImportError:
            pass

        # 旧版兼容 tracking
        self._blocked_paths: set[str] = set()
        self._path_failures: dict[str, int] = {}
        self._banned_paths: set[str] = set()
        self._escalated_to_playwright: bool = False
        self._pw_escalation_time: float = 0.0

        # 统计
        self._stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "pipeline_calls": 0,
        }

    async def __aenter__(self) -> HLTVClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """关闭所有连接。"""
        await self._session_pool.close()
        if self._archive:
            self._archive.close()

    # ── 公共接口（向后兼容） ──────────────────────────────

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
        """Fetch an HLTV page with automatic fallback and caching.

        与旧版接口完全兼容。
        内部使用 FetchPipeline + 内联 transport fallback。

        Args:
            url: Target URL.
            use_curl: Force curl_cffi as primary.
            force_playwright: Force browser rendering.
            cache_ttl: Override cache TTL.
            cache_key: Custom cache key (defaults to URL).

        Returns:
            HTML response text.
        """
        self._stats["total_requests"] += 1
        ck = cache_key or url

        # 1. 内存缓存
        if self._mem_cache is not None:
            mem_cached = self._mem_cache.get(ck)
            if mem_cached is not None:
                self._stats["cache_hits"] += 1
                logger.debug("Memory cache HIT: %s", url)
                return str(mem_cached)

        # 2. 磁盘缓存
        cached = self.cache.get(ck)
        if cached is not None:
            self._stats["cache_hits"] += 1
            logger.debug("Disk cache HIT: %s", url)
            if self._mem_cache is not None:
                self._mem_cache[ck] = cached
            return str(cached)

        logger.debug("Fetching: %s", url)
        self._stats["pipeline_calls"] += 1

        # 3. 尝试新版 pipeline
        try:
            request = FetchRequest(
                url=url,
                cache_ttl=cache_ttl or self.config.cache.ttl,
                cache_key=ck,
                force_playwright=force_playwright,
                prefer_curl=use_curl or self.config.client.curl_impersonate,
            )
            response = await self._pipeline.execute(request)
            html = response.html
            self._cache_set(ck, html, ttl=cache_ttl)
            return html
        except Exception as e:
            logger.debug("Pipeline failed, using inline fallback: %s", e)

        # 4. 内联 transport fallback（兼容旧版行为）
        return await self._inline_fetch(
            url=url,
            use_curl=use_curl,
            force_playwright=force_playwright,
            cache_key=ck,
            cache_ttl=cache_ttl,
            **kwargs,
        )

    async def _inline_fetch(
        self,
        url: str,
        use_curl: bool = False,
        force_playwright: bool = False,
        cache_key: str | None = None,
        cache_ttl: int | None = None,
        **kwargs: Any,
    ) -> str:
        """内联 transport fallback（与新 pipeline 逻辑等价但更直接）。"""
        ck = cache_key or url

        # Playwright escalation TTL 检查
        if self._escalated_to_playwright and (tmod.time() - self._pw_escalation_time) > 600:
            self._escalated_to_playwright = False

        # 3-strike path ban
        parsed = urlparse(url)
        path = parsed.path
        if path in self._banned_paths:
            raise BlockedError(url=url, message=f"Path banned: {url}")

        # Rate limit
        allowed = await self._rate_limiter.acquire(url)
        if not allowed:
            raise RateLimitError(url=url, message=f"Rate limit: {url}")

        # Transport 选择
        transport = "playwright" if force_playwright else (
            self._session_pool.best_transport(url, self.config.client.mode == "stealth")
        )

        # 执行并 fallback
        errors: list[Exception] = []
        transports_to_try = [transport]

        if transport == "curl":
            transports_to_try.append("httpx")
        elif transport == "httpx":
            transports_to_try.insert(0, "curl")

        if self.config.client.mode == "stealth" and "playwright" not in transports_to_try:
            transports_to_try.append("playwright")

        for t in transports_to_try:
            try:
                session = await self._session_pool.acquire(t)
                if session is None or session.client is None:
                    continue

                profile = random_profile()
                headers = profile.to_dict(referer=random_referer())
                headers["Accept-Language"] = random_accept_language()

                if session.cookie_jar:
                    cookie_str = "; ".join(
                        f"{k}={v}" for k, v in session.cookie_jar.items()
                    )
                    headers["Cookie"] = cookie_str

                text, status_code = await self._transport_request(t, session, url, headers)

                # Block 检测
                block_result = self._block_detector.combine_checks(
                    status_code=status_code, text=text, url=url, response_time=0.0,
                )
                if block_result["blocked"]:
                    self._session_pool.release(session.id, success=False)
                    self._track_path_failure(url)
                    if t == "curl":
                        continue  # 试下一个 transport
                    raise BlockedError(url=url, message=f"{block_result['block_type']}: {url}")

                self._session_pool.release(session.id, success=True)
                self._rate_limiter.report_success(url)
                self._cache_set(ck, text, ttl=cache_ttl)
                return text

            except (ImportError, BlockedError, HTTPError) as e:
                errors.append(e)
                if isinstance(e, BlockedError) and t == "curl" and self.config.client.mode == "stealth":
                    self._escalated_to_playwright = True
                    self._pw_escalation_time = tmod.time()
                continue
            except Exception as e:
                errors.append(e)
                continue

        error_msg = "; ".join(f"{type(e).__name__}: {e}" for e in errors)
        raise HTTPError(url=url, message=f"All transports failed: {error_msg}")

    async def _transport_request(
        self,
        transport: str,
        session: Any,
        url: str,
        headers: dict,
    ) -> tuple[str, int]:
        """用指定的 transport 发送请求。"""
        if transport == "curl":
            response = await session.client.get(url, headers=headers)
            self._extract_cookies(session, response.headers)
            return response.text, response.status_code

        elif transport == "httpx":
            response = await session.client.get(url, headers=headers)
            self._extract_cookies(session, response.headers)
            return response.text, response.status_code

        elif transport == "playwright":
            context = session.client
            page = await context.new_page()
            await page.add_init_script("""
                Object.defineProperties(navigator, {
                    webdriver: { get: () => false },
                    plugins: { get: () => [1, 2, 3, 4, 5] },
                    languages: { get: () => ['en-US', 'en'] },
                });
            """)
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(1.0)
            content = await page.content()
            await page.close()
            return content, 200

        raise ValueError(f"Unknown transport: {transport}")

    def _extract_cookies(self, session: Any, headers: Any) -> None:
        try:
            set_cookie = None
            if hasattr(headers, "getall"):
                set_cookie = headers.getall("set-cookie", [])
            elif hasattr(headers, "get_list"):
                set_cookie = headers.get_list("set-cookie")
            elif hasattr(headers, "get"):
                val = headers.get("set-cookie")
                set_cookie = [val] if val else []

            if set_cookie:
                for h in set_cookie:
                    parts = h.split(";")[0]
                    if "=" in parts:
                        name, value = parts.split("=", 1)
                        session.cookie_jar[name.strip()] = value.strip()
        except Exception:
            pass

    def _track_path_failure(self, url: str) -> None:
        parsed = urlparse(url)
        path = parsed.path
        self._blocked_paths.add(path)
        if len(self._blocked_paths) > 500:
            self._blocked_paths.clear()
        self._path_failures[path] = self._path_failures.get(path, 0) + 1
        if self._path_failures[path] >= 3:
            self._banned_paths.add(path)

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
            **kwargs: Additional arguments for get().

        Returns:
            Parsed tree (selectolax HTMLParser or BeautifulSoup).
        """
        html = await self.get(url, **kwargs)
        if _HAS_SELECTOLAX:
            from selectolax.parser import HTMLParser
            return HTMLParser(html)
        return BeautifulSoup(html, parser)

    def _cache_set(self, key: str, value: str, ttl: int | None = None) -> None:
        if self._mem_cache is not None:
            self._mem_cache[key] = value
        self.cache.set(key, value, ttl=ttl)

    def clear_cache(self) -> None:
        if self._mem_cache is not None:
            self._mem_cache.clear()
        self.cache.clear()
        logger.info("Cache cleared")

    def get_client_stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "pipeline": self._pipeline.get_stats(),
            "rate_limiter": self._rate_limiter.get_stats(),
            "session_pool": self._session_pool.get_stats(),
        }
