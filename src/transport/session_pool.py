from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from .base import TransportSession
from .fingerprint import TLSFingerprintManager
from .pool.curl_pool import CurlSessionPool
from .pool.httpx_pool import HttpxSessionPool
from .pool.playwright_pool import PlaywrightContextPool

logger = logging.getLogger("hltv.transport.session_pool")


class SessionPool:
    """
    多 session 管理池。

    核心职责：
    1. 维护多个 TransportSession，每个有独立指纹 + cookie
    2. 按 health_score 选择最优 session
    3. 自动创建新 session，回收死亡/过期 session
    4. 被封 session 隔离，不影响其他 session

    架构：
    - curl 池：10-15 个 session，各独立 fingerprint
    - httpx 池：3-5 个 session（备用）
    - Playwright 池：2 个 context（核选项）

    选择策略：
    - 每次从池中选出 health_score 最高的 session
    - 加入随机噪声防止饥饿
    - 连续失败 3 次 → ban → 5min 后 unban
    """

    def __init__(
        self,
        curl_count: int = 10,
        httpx_count: int = 3,
        playwright_count: int = 1,
        config: Any | None = None,
    ) -> None:
        self._config = config
        self._fingerprint_mgr = TLSFingerprintManager()

        # 具体的传输层池
        self._curl_pool = CurlSessionPool(
            size=curl_count,
            fingerprint_mgr=self._fingerprint_mgr,
            config=config,
        )
        self._httpx_pool = HttpxSessionPool(
            size=httpx_count,
            fingerprint_mgr=self._fingerprint_mgr,
            config=config,
        )
        self._playwright_pool = PlaywrightContextPool(
            size=playwright_count,
            config=config,
        )

        self._lock = asyncio.Lock()

    async def acquire(
        self,
        transport: Literal["curl", "httpx", "playwright"] = "curl",
    ) -> TransportSession:
        """
        获取一个 transport session。

        Args:
            transport: 传输层类型。

        Returns:
            health_score 最高的 session。

        Raises:
            RuntimeError: 如果所有 session 都不可用。
        """
        pool = self._get_pool(transport)
        session = await pool.acquire()
        if session is None:
            raise RuntimeError(
                f"No available {transport} sessions (all banned or expired)",
            )
        return session

    def release(self, session_id: str, success: bool = True) -> None:
        """释放一个 session（由 FetchPipeline 调用）。"""
        for pool in self._pools:
            pool.release(session_id, success)

    async def close(self) -> None:
        """关闭所有传输层连接。"""
        for pool in self._pools:
            await pool.close()

    @property
    def _pools(self) -> list:
        return [self._curl_pool, self._httpx_pool, self._playwright_pool]

    def _get_pool(self, transport: str):
        if transport == "curl":
            return self._curl_pool
        elif transport == "httpx":
            return self._httpx_pool
        elif transport == "playwright":
            return self._playwright_pool
        raise ValueError(f"Unknown transport: {transport}")

    def best_transport(self, url: str, stealth_mode: bool = False) -> str:
        """
        确定最佳传输层。

        策略：
        1. 如果有 curl session 可用且未被 ban → curl
        2. 如果 curl 全 ban 了 → httpx
        3. 如果是 stealth mode 且需要 → playwright
        4. 从 playwright 降级下来时尝试 curl
        """
        curl_ok = self._curl_pool.has_available()
        httpx_ok = self._httpx_pool.has_available()

        if stealth_mode and not curl_ok and not httpx_ok:
            return "playwright"
        if curl_ok:
            return "curl"
        if httpx_ok:
            return "httpx"
        return "playwright"

    def get_stats(self) -> dict[str, Any]:
        return {
            "curl": {
                "total": self._curl_pool.size,
                "available": self._curl_pool.available_count(),
                "banned": self._curl_pool.banned_count(),
                "sessions": [s.to_dict() for s in self._curl_pool.sessions],
            },
            "httpx": {
                "total": self._httpx_pool.size,
                "available": self._httpx_pool.available_count(),
                "banned": self._httpx_pool.banned_count(),
                "sessions": [s.to_dict() for s in self._httpx_pool.sessions],
            },
            "playwright": {
                "total": self._playwright_pool.size,
                "available": self._playwright_pool.available_count(),
                "sessions": [s.to_dict() for s in self._playwright_pool.sessions],
            },
        }
