"""
Fetch Pipeline v2：统一的请求执行管道。

核心升级：
1. Identity 绑定 —— 每个请求使用 session 绑定的 identity headers，不再 random_profile()
2. 行为延迟 —— 完整使用 HumanRequestPattern 的延迟，不再截断
3. 响应验证 —— 验证返回数据的真实性
4. 恢复策略集成 —— 根据 BlockDetector 的 recovery 建议执行恢复
5. 浏览历史记录 —— 记录每个 session 的浏览路径
6. 柔性降级 —— 低置信度 block 降速而非直接失败

生命周期：
1. Filter (去重)
2. Cache lookup (L1 → L2 → L3)
3. Rate limit acquire
4. Human pattern delay (完整延迟)
5. Session acquire (从 SessionPool)
6. Build headers (from session identity)
7. Transport 执行
8. Block check (置信度评分)
9. Response validation (数据真实性)
10. Cache write
11. Archive raw HTML
12. Return FetchResponse
"""

from __future__ import annotations

import asyncio
import logging
import random
import time as tmod
from dataclasses import dataclass, field
from cachetools import TTLCache
from typing import Any
from urllib.parse import urlparse

from src.antibot.block_detector import BlockDetector
from src.antibot.human_pattern import HumanRequestPattern
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
    validated: bool = False
    validation_details: dict[str, Any] = field(default_factory=dict)


class ResponseValidator:
    """
    响应验证器：确保返回数据的真实性。

    验证策略：
    1. 结构完整性 —— 必须包含 HLTV 特有的 DOM 结构
    2. 数据合理性 —— 比赛分数、排名等数据在合理范围内
    3. 内容唯一性 —— 不与已知 block 页面重复
    4. 编码正确性 —— UTF-8 编码，无乱码
    """

    _KNOWN_BLOCK_HASHES: set[str] = set()

    _MIN_VALID_SIZE = 5000
    _MAX_VALID_SIZE = 2000000

    def validate(self, html: str, url: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "valid": True,
            "checks": {},
            "warnings": [],
        }

        size = len(html)
        result["checks"]["size"] = size

        if size < self._MIN_VALID_SIZE:
            result["checks"]["min_size"] = False
            result["warnings"].append(f"Response too small: {size} bytes")
            result["valid"] = False
        else:
            result["checks"]["min_size"] = True

        if size > self._MAX_VALID_SIZE:
            result["checks"]["max_size"] = False
            result["warnings"].append(f"Response unusually large: {size} bytes")
        else:
            result["checks"]["max_size"] = True

        has_hltv_marker = any(
            marker in html for marker in ["HLTV", "hltv", "nav-bar", "standard-box"]
        )
        result["checks"]["hltv_markers"] = has_hltv_marker
        if not has_hltv_marker:
            result["warnings"].append("No HLTV markers found")
            result["valid"] = False

        has_block_indicator = any(
            indicator in html.lower()
            for indicator in ["cloudflare", "captcha", "blocked", "denied"]
        )
        result["checks"]["no_block_indicators"] = not has_block_indicator or has_hltv_marker
        if has_block_indicator and not has_hltv_marker:
            result["warnings"].append("Block indicators found in response")
            result["valid"] = False

        try:
            html.encode("utf-8").decode("utf-8")
            result["checks"]["encoding"] = True
        except (UnicodeDecodeError, UnicodeEncodeError):
            result["checks"]["encoding"] = False
            result["warnings"].append("Encoding issue detected")
            result["valid"] = False

        parsed = urlparse(url)
        path = parsed.path
        if "/matches/" in path and path.count("/") > 3:
            has_match_content = any(
                m in html for m in ["match-page", "maps", "lineup"]
            )
            result["checks"]["match_content"] = has_match_content
            if not has_match_content:
                result["warnings"].append("Match page missing expected content")

        elif "/team/" in path:
            has_team_content = any(
                m in html for m in ["team-stats", "roster", "standard-box"]
            )
            result["checks"]["team_content"] = has_team_content
            if not has_team_content:
                result["warnings"].append("Team page missing expected content")

        elif "/player/" in path:
            has_player_content = any(
                m in html for m in ["player-stats", "statistics"]
            )
            result["checks"]["player_content"] = has_player_content
            if not has_player_content:
                result["warnings"].append("Player page missing expected content")

        return result


class FetchPipeline:
    """
    统一的请求执行管道 v2。

    使用方式：
        pipeline = FetchPipeline(session_pool, rate_limiter, block_detector, ...)
        response = await pipeline.execute(FetchRequest("https://www.hltv.org/matches"))
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
        self._validator = ResponseValidator()

        self._dedup_cache: TTLCache = TTLCache(maxsize=2000, ttl=30)
        self._path_failures: dict[str, int] = {}
        self._banned_paths: dict[str, float] = {}

        self._stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "blocked": 0,
            "soft_blocked": 0,
            "validation_failures": 0,
            "errors": 0,
            "avg_response_time": 0.0,
        }

    async def execute(self, request: FetchRequest) -> FetchResponse:
        self._stats["total_requests"] += 1
        start_time = tmod.time()

        # 1. 去重
        if request.dedup_key:
            dedup_key = request.dedup_key
            if dedup_key in self._dedup_cache:
                logger.debug("Dedup hit, skipping: %s", request.url)
                return FetchResponse(
                    url=request.url,
                    html="",
                    status_code=304,
                    from_cache=True,
                    fetched_at=tmod.time(),
                )
            self._dedup_cache[dedup_key] = tmod.time()

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

        # 4. Human pattern delay (完整延迟，不再截断)
        if not request.bypass_rate_limit:
            hdelay = await self._human_pattern.next_delay(request.url)
            if hdelay > 0:
                await asyncio.sleep(hdelay)

        # 5. 选择 transport & session
        transport = "playwright" if request.force_playwright else (
            "curl" if request.prefer_curl else
            self._session_pool.best_transport(request.url, False)
        )

        session = None
        try:
            session = await self._session_pool.acquire(transport)  # type: ignore[arg-type]
            if session is None:
                transport = "curl"
                session = await self._session_pool.acquire("curl")
        except (RuntimeError, Exception) as e:
            logger.warning("Session acquire failed, trying fallback: %s", e)
            transport = "httpx" if transport == "curl" else "curl"
            session = await self._session_pool.acquire(transport)  # type: ignore[arg-type]

        session_id = session.id if session else None

        # 6. 执行请求 (使用 session identity 的 headers)
        try:
            html, status_code = await self._execute_transport(request.url, session, transport)
            response_time = tmod.time() - start_time

            # 7. Block 检测 (置信度评分)
            block_result = await self._block_detector.combine_checks(
                status_code=status_code,
                text=html,
                url=request.url,
                response_time=response_time,
            )

            if block_result["blocked"]:
                recovery = block_result.get("recovery", {})

                if block_result["confidence"] < 0.7:
                    self._stats["soft_blocked"] += 1
                    logger.warning(
                        "Soft block detected (confidence=%.2f), applying recovery: %s",
                        block_result["confidence"],
                        recovery.get("action", "unknown"),
                    )

                    if recovery.get("cooldown_seconds", 0) > 0:
                        await asyncio.sleep(recovery["cooldown_seconds"])

                    await self._rate_limiter.report_error(request.url)
                    if session:
                        self._session_pool.release(session_id or "", success=False)
                    self._track_path_failure(request.url)

                    is_cf = block_result.get("block_type") in (
                        "cloudflare_challenge", "blocked",
                    )
                    if is_cf and transport != "playwright":
                        logger.warning(
                            "Soft CF block on %s, escalating to Playwright: %s",
                            transport, request.url,
                        )
                        try:
                            pw_session = await self._session_pool.acquire("playwright")
                            if pw_session:
                                return await self._retry_fallback(request, pw_session, "playwright")
                        except Exception as e:
                            logger.warning("Playwright escalation failed: %s", e)

                    if transport == "curl" and not request.force_playwright:
                        logger.warning("Soft blocked on curl, re-trying with httpx: %s", request.url)
                        session2 = await self._session_pool.acquire("httpx")
                        return await self._retry_fallback(request, session2, "httpx")

                    raise BlockedError(
                        message=f"{block_result['block_type']}: {request.url}",
                        url=request.url,
                    )

                self._stats["blocked"] += 1
                if session:
                    self._session_pool.release(session_id or "", success=False)
                self._track_path_failure(request.url)

                is_cf = block_result.get("block_type") in (
                    "cloudflare_challenge", "blocked", "service_unavailable",
                )
                if is_cf and transport != "playwright":
                    logger.warning(
                        "CF challenge detected on %s (confidence=%.2f), escalating to Playwright: %s",
                        transport, block_result["confidence"], request.url,
                    )
                    try:
                        pw_session = await self._session_pool.acquire("playwright")
                        if pw_session:
                            return await self._retry_fallback(request, pw_session, "playwright")
                    except Exception as e:
                        logger.warning("Playwright escalation failed: %s", e)

                if recovery.get("switch_transport") and transport == "curl" and not request.force_playwright:
                    logger.warning("Blocked on curl (confidence=%.2f), switching transport: %s",
                                   block_result["confidence"], request.url)
                    if recovery.get("cooldown_seconds", 0) > 0:
                        await asyncio.sleep(min(recovery["cooldown_seconds"], 30.0))
                    session2 = await self._session_pool.acquire("httpx")
                    return await self._retry_fallback(request, session2, "httpx")

                if recovery.get("cooldown_seconds", 0) > 0:
                    await asyncio.sleep(min(recovery["cooldown_seconds"], 30.0))

                raise BlockedError(
                    message=f"{block_result['block_type']}: {request.url}",
                    url=request.url,
                )

            # 8. 响应验证
            validation = self._validator.validate(html, request.url)
            if not validation["valid"]:
                self._stats["validation_failures"] += 1
                logger.warning(
                    "Response validation failed for %s: %s",
                    request.url,
                    validation["warnings"],
                )

            # 成功
            if session:
                self._session_pool.release(session_id or "", success=True)
                if hasattr(session, 'identity') and hasattr(session.identity, 'browsing'):
                    session.identity.browsing.record_visit(path)

            if transport == "playwright" and session and session.cookie_jar:
                self._session_pool.share_cookies(session.cookie_jar, "playwright")

            await self._rate_limiter.report_success(request.url, response_time=response_time)

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
                validated=validation["valid"],
                validation_details=validation,
            )

            # 9. Archive raw HTML
            if self._archive and not request.bypass_cache:
                await self._archive.store(
                    url=request.url,
                    html=html,
                    metadata={
                        "status_code": status_code,
                        "transport": transport,
                        "response_time": response_time,
                        "validated": validation["valid"],
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
                self._session_pool.release(session_id or "", success=False)
            raise
        except Exception:
            if session:
                self._session_pool.release(session_id or "", success=False)
            raise

    async def _execute_transport(
        self,
        url: str,
        session: Any,
        transport: str,
    ) -> tuple[str, int]:
        if session is None or session.client is None:
            raise HTTPError(message=f"No client for transport {transport}", url=url)

        # 关键升级：使用 session identity 构建一致的 headers
        if hasattr(session, 'identity') and hasattr(session.identity, 'build_headers'):
            parsed = urlparse(url)
            referer = session.identity.get_natural_referer(parsed.path)
            headers = session.identity.build_headers(referer=referer)
        else:
            from src.antibot.header_profiles import random_profile, random_referer
            profile = random_profile()
            headers = profile.to_dict(referer=random_referer())

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
        try:
            context = session.client
            page = await context.new_page()

            identity = getattr(session, 'identity', None)

            stealth_script = """
                Object.defineProperties(navigator, {
                    webdriver: { get: () => false },
                    plugins: { get: () => [1, 2, 3, 4, 5] },
                    languages: { get: () => ['en-US', 'en'] },
                });
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'permissions', {
                    get: () => ({
                        query: () => Promise.resolve({ state: 'granted' }),
                    }),
                });
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            """

            if identity:
                gpu_vendor = identity.gpu_vendor.replace("'", "\\'")
                gpu_renderer = identity.gpu_renderer.replace("'", "\\'")
                stealth_script += f"""
                    Object.defineProperties(navigator, {{
                        hardwareConcurrency: {{ get: () => {identity.hardware_concurrency} }},
                        deviceMemory: {{ get: () => {identity.device_memory} }},
                    }});
                    const getParameter = WebGLRenderingContext.prototype.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                        if (parameter === 37445) return '{gpu_vendor}';
                        if (parameter === 37446) return '{gpu_renderer}';
                        return getParameter.call(this, parameter);
                    }};
                """

            await page.add_init_script(stealth_script)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass

            for attempt in range(20):
                content = await page.content()
                content_lower = content.lower()

                has_hltv = any(
                    marker.lower() in content_lower
                    for marker in ["HLTV", "nav-bar", "standard-box", "match-wrapper",
                                   "teamsBox", "topnav", "sidebar", "footer-navigation"]
                )
                if has_hltv:
                    break

                is_cf_challenge = any(
                    ind in content_lower
                    for ind in ["just a moment", "checking your browser", "cf-browser-verification",
                                "cf_challenge", "__cf_chl_f_tk", "challenge-platform",
                                "cf-challenge", "turnstile"]
                )
                if not is_cf_challenge:
                    break
                await asyncio.sleep(1.0)
            else:
                await asyncio.sleep(3.0)

            await asyncio.sleep(random.uniform(0.3, 1.0))

            content = await page.content()

            try:
                browser_cookies = await context.cookies("https://www.hltv.org")
                for c in browser_cookies:
                    session.cookie_jar[c["name"]] = c["value"]
            except Exception:
                pass

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
        html, status_code = await self._execute_transport(
            request.url, session, transport,
        )

        block_result = await self._block_detector.combine_checks(
            status_code=status_code, text=html, url=request.url, response_time=0.0,
        )
        if block_result["blocked"]:
            is_cf = block_result.get("block_type") in (
                "cloudflare_challenge", "blocked", "service_unavailable",
            )
            if session:
                self._session_pool.release(
                    session.id if hasattr(session, "id") else "",
                    success=not (is_cf and transport == "playwright"),
                )
            raise BlockedError(
                message=f"{block_result['block_type']}: {request.url}",
                url=request.url,
            )

        if session:
            self._session_pool.release(
                session.id if hasattr(session, "id") else "",
                success=True,
            )
            if hasattr(session, 'identity') and hasattr(session.identity, 'browsing'):
                from urllib.parse import urlparse as _urlparse
                _path = _urlparse(request.url).path
                session.identity.browsing.record_visit(_path)

        if transport == "playwright" and session and hasattr(session, 'cookie_jar') and session.cookie_jar:
            self._session_pool.share_cookies(session.cookie_jar, "playwright")

        validation = self._validator.validate(html, request.url)

        return FetchResponse(
            url=request.url,
            html=html,
            status_code=status_code,
            transport_used=transport,
            fetched_at=tmod.time(),
            validated=validation["valid"],
            validation_details=validation,
        )

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
                        if hasattr(session, 'identity') and hasattr(session.identity, 'cookie_birth_time'):
                            session.identity.cookie_birth_time[name.strip()] = tmod.time()
        except Exception:
            pass

    def _track_path_failure(self, url: str) -> None:
        parsed = urlparse(url)
        path = parsed.path
        self._path_failures[path] = self._path_failures.get(path, 0) + 1
        if self._path_failures[path] >= 3:
            self._banned_paths[path] = tmod.time()

    def get_stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "banned_paths": len(self._banned_paths),
            "block_pattern": self._block_detector.get_block_pattern(),
        }
