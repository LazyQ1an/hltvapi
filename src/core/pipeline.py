"""
Fetch Pipeline：统一的请求执行管道。

生命周期：
1. Filter (去重)
2. Cache lookup (L1 → L2 → L3)
3. Rate limit acquire
4. Session acquire (从 SessionPool)
5. Transport 执行
6. Block check (多层检测)
7. Cache write
8. Archive raw HTML
9. Return FetchResponse
"""

from __future__ import annotations

import asyncio
import logging
import time as tmod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from src.antibot.block_detector import BlockDetector
from src.antibot.human_pattern import HumanRequestPattern
from src.antibot.header_profiles import random_profile, random_referer, random_accept_language
from src.antibot.rate_limiter import AdaptiveRateLimiter
from src.exceptions import BlockedError, HTTPError, RateLimitError
from src.transport.session_pool import SessionPool
from src.storage.archive import HTMLArchive

logger = logging.getLogger("hltv.core.pipeline")


@dataclass
class FetchRequest:
    url: str
    cache_ttl: int | None = None
    cache_key: str | None = None
    force_playwright: bool = False
    prefer_curl: bool = False
    bypass_cache: bool = False
    bypass_rate_limit: bool = False
    priority: int = 0
    dedup_key: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class FetchResponse:
    url: str
    html: str
    status_code: int = 200
    transport_used: str = ""
    session_id: str | None = None
    from_cache: bool = False
    fetched_at: float = 0.0
    ttl: int | None = None
    response_time: float = 0.0


class FetchPipeline:
    """
    统一的请求执行管道。

    使用方式：
        pipeline = FetchPipeline(session_pool, rate_limiter, block_detector, ...)
        response = await pipeline.execute(FetchRequest("https://www.hltv.org/matches"))

    与旧版 client.py 的 get() 方法兼容。
    """

    def __init__(
        self,
        session_pool: SessionPool,
        rate_limiter: AdaptiveRateLimiter | None = None,
        block_detector: BlockDetector | None = None,
        human_pattern: HumanRequestPattern | None = None,
        archive: HTMLArchive | None = None,
        config: Any = None,
    ) -> None:
        self._session_pool = session_pool
        self._rate_limiter = rate_limiter or AdaptiveRateLimiter()
        self._block_detector = block_detector or BlockDetector()
        self._human_pattern = human_pattern or HumanRequestPattern()
        self._archive = archive
        self._config = config

        # 去重缓存
        self._dedup_cache: dict[str, float] = {}
        self._path_failures: dict[str, int] = {}
        self._banned_paths: dict[str, float] = {}

        self._stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "blocked": 0,
            "errors": 0,
            "avg_response_time": 0.0,
        }

    async def execute(self, request: FetchRequest) -> FetchResponse:
        """执行一个请求，返回 FetchResponse。"""
        self._stats["total_requests"] += 1
        start_time = tmod.time()

        # 1. 去重
        if request.dedup_key:
            dedup_key = request.dedup_key
            now = tmod.time()
            if dedup_key in self._dedup_cache and (now - self._dedup_cache[dedup_key]) < 5:
                logger.debug("Dedup hit, skipping: %s", request.url)
                raise HTTPError(message=f"Dedup: {request.url}", url=request.url)
            self._dedup_cache[dedup_key] = now
            # 清理
            if len(self._dedup_cache) > 1000:
                cutoff = now - 10
                self._dedup_cache = {k: v for k, v in self._dedup_cache.items() if v > cutoff}

        # 2. Path 封禁检查
        parsed = urlparse(request.url)
        path = parsed.path
        if path in self._banned_paths:
            ban_time = self._banned_paths[path]
            if (tmod.time() - ban_time) < 300:
                raise BlockedError(
                    message=f"Path temporarily banned: {request.url}",
                    url=request.url,
                )
            else:
                del self._banned_paths[path]

        # 3. Rate limit
        if not request.bypass_rate_limit:
            allowed = await self._rate_limiter.acquire(request.url)
            if not allowed:
                raise RateLimitError(
                    message=f"Rate limit: {request.url}",
                    url=request.url,
                )

        # 4. Human pattern delay
        if not request.bypass_rate_limit:
            hdelay = await self._human_pattern.next_delay(request.url)
            if hdelay > 0:
                await asyncio.sleep(min(hdelay, 0.1))  # 10ms base, burst 模式在 rate limiter 里

        # 5. 选择 transport & session
        transport = "playwright" if request.force_playwright else (
            "curl" if request.prefer_curl else
            self._session_pool.best_transport(request.url, False)
        )

        session = None
        try:
            session = await self._session_pool.acquire(transport)
            if session is None:
                transport = "curl"
                session = await self._session_pool.acquire("curl")
        except (RuntimeError, Exception) as e:
            logger.warning("Session acquire failed, trying fallback: %s", e)
            transport = "httpx" if transport == "curl" else "curl"
            session = await self._session_pool.acquire(transport)

        session_id = session.id if session else None

        # 6. 执行请求
        try:
            html, status_code = await self._execute_transport(request.url, session, transport)
            response_time = tmod.time() - start_time

            # 7. Block 检测
            block_result = self._block_detector.combine_checks(
                status_code=status_code,
                text=html,
                url=request.url,
                response_time=response_time,
            )
            if block_result["blocked"]:
                self._stats["blocked"] += 1
                if session:
                    self._session_pool.release(session_id, success=False)
                self._track_path_failure(request.url)

                if transport == "curl" and not request.force_playwright:
                    logger.warning("Blocked on curl, re-trying with httpx: %s", request.url)
                    session2 = await self._session_pool.acquire("httpx")
                    return await self._retry_fallback(request, session2, "httpx")

                raise BlockedError(
                    message=f"{block_result['block_type']}: {request.url}",
                    url=request.url,
                )

            # 成功
            if session:
                self._session_pool.release(session_id, success=True)
            self._rate_limiter.report_success(request.url)

            fetched_at = tmod.time()
            response = FetchResponse(
                url=request.url,
                html=html,
                status_code=status_code,
                transport_used=transport,
                session_id=session_id,
                from_cache=False,
                fetched_at=fetched_at,
                ttl=request.cache_ttl,
                response_time=response_time,
            )

            # 8. Archive raw HTML
            if self._archive and not request.bypass_cache:
                await self._archive.store(
                    url=request.url,
                    html=html,
                    metadata={
                        "status_code": status_code,
                        "transport": transport,
                        "response_time": response_time,
                    },
                )

            # 更新统计
            n = self._stats["total_requests"]
            self._stats["avg_response_time"] = (
                (self._stats["avg_response_time"] * (n - 1) + response_time) / n
            )

            return response

        except (BlockedError, HTTPError, RateLimitError):
            if session:
                self._session_pool.release(session_id, success=False)
            raise

    async def _execute_transport(
        self,
        url: str,
        session: Any,
        transport: str,
    ) -> tuple[str, int]:
        """用指定 transport + session 执行请求。"""
        if session is None or session.client is None:
            raise HTTPError(message=f"No client for transport {transport}", url=url)

        profile = random_profile()
        headers = profile.to_dict(referer=random_referer())
        headers["Accept-Language"] = random_accept_language()

        if session.cookie_jar:
            cookie_str = "; ".join(
                f"{k}={v}" for k, v in session.cookie_jar.items()
            )
            headers["Cookie"] = cookie_str

        if transport == "curl":
            try:
                response = await session.client.get(url, headers=headers)
                self._extract_cookies(session, response.headers)
                return response.text, response.status_code
            except Exception as e:
                raise HTTPError(
                    message=f"curl_cffi request failed: {e}",
                    url=url, status_code=0,
                )

        elif transport == "httpx":
            try:
                response = await session.client.get(url, headers=headers)
                self._extract_cookies(session, response.headers)
                return response.text, response.status_code
            except Exception as e:
                raise HTTPError(
                    message=f"httpx request failed: {e}",
                    url=url, status_code=0,
                )

        elif transport == "playwright":
            return await self._execute_playwright(url, session)

        raise HTTPError(message=f"Unknown transport: {transport}", url=url)

    async def _execute_playwright(self, url: str, session: Any) -> tuple[str, int]:
        """通过 Playwright 执行请求。"""
        try:
            context = session.client
            page = await context.new_page()

            # Stealth init
            await page.add_init_script("""
                Object.defineProperties(navigator, {
                    webdriver: { get: () => false },
                    plugins: { get: () => [1, 2, 3, 4, 5] },
                    languages: { get: () => ['en-US', 'en'] },
                    hardwareConcurrency: { get: () => 8 },
                    deviceMemory: { get: () => 8 },
                });
            """)

            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(1.0)
            content = await page.content()
            await page.close()
            return content, 200
        except Exception as e:
            raise HTTPError(
                message=f"Playwright request failed: {e}",
                url=url,
            )

    async def _retry_fallback(
        self,
        request: FetchRequest,
        session: Any,
        transport: str,
    ) -> FetchResponse:
        """当 primary transport 被封时用 fallback 重试。"""
        html, status_code = await self._execute_transport(
            request.url, session, transport,
        )
        if session:
            self._session_pool.release(
                session.id if hasattr(session, "id") else "",
                success=True,
            )
        return FetchResponse(
            url=request.url,
            html=html,
            status_code=status_code,
            transport_used=transport,
            fetched_at=tmod.time(),
        )

    def _extract_cookies(self, session: Any, headers: Any) -> None:
        """从响应头提取 cookies。"""
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
        self._path_failures[path] = self._path_failures.get(path, 0) + 1
        if self._path_failures[path] >= 3:
            self._banned_paths[path] = tmod.time()

    def get_stats(self) -> dict[str, Any]:
        return {**self._stats, "banned_paths": len(self._banned_paths)}
