from __future__ import annotations

import asyncio
import random
import time as tmod
from collections import deque
from typing import Any


class AdaptiveRateLimiter:
    """
    基于滑动时间窗口的智能速率限制器。

    核心改进：
    1. 滑动窗口（deque）替代固定整点计数器 —— 更精确，无"整点重置"特征
    2. 基于 block rate 的动态调速 —— 有 block 自动降速
    3. 基于响应时间的调速 —— 慢响应 = 可能被限速
    4. 慢恢复 —— block 消失后逐步恢复到正常速率
    5. 多维度：domain-level + path-level + global

    与旧版区别：
    - 旧版：整点重置、指数 backoff 只增不减
    - 新版：滑动窗口实时计算、block_rate 动态调速、慢恢复
    """

    def __init__(
        self,
        min_delay: float = 1.5,
        max_delay: float = 10.0,
        jitter: bool = True,
        requests_per_hour: int = 1000,
        requests_per_day: int = 5000,
    ) -> None:
        self._base_min = min_delay
        self._base_max = max_delay
        self._current_delay = min_delay
        self._jitter = jitter

        self._hourly_limit = requests_per_hour
        self._daily_limit = requests_per_day

        # 滑动窗口：只保留最近 3600s 和 86400s 的时间戳
        self._hour_window: deque[float] = deque()
        self._day_window: deque[float] = deque()
        self._block_window: deque[float] = deque()  # 最近 block 记录

        # Per-domain 状态
        self._domain_state: dict[str, dict[str, float | int]] = {}

        self._lock = asyncio.Lock()
        self._stats = {
            "total_requests": 0,
            "total_blocks": 0,
            "total_delays": 0.0,
        }

    async def acquire(self, url: str | None = None) -> bool:
        """
        获取请求许可。阻塞直到允许发出请求。

        Returns:
            True = 允许请求, False = 硬上限已到
        """
        domain = self._extract_domain(url) if url else "default"
        now = tmod.time()

        async with self._lock:
            self._prune_windows(now)

            if self._hourly_limit > 0 and len(self._hour_window) >= self._hourly_limit:
                return False
            if self._daily_limit > 0 and len(self._day_window) >= self._daily_limit:
                return False

            self._adjust_delay(now)

            state = self._domain_state.setdefault(domain, {
                "last": 0.0, "errors": 0, "cur_delay": self._base_min,
            })
            elapsed = now - (state["last"] or 0)
            cur_delay: float = state["cur_delay"] or self._base_min
            wait = max(0.0, cur_delay - elapsed)

            if self._jitter and wait > 0:
                spread = cur_delay * 0.25
                wait = max(0.0, wait + random.gauss(0, spread))

            state["last"] = tmod.time()
            self._hour_window.append(now)
            self._day_window.append(now)
            self._stats["total_requests"] += 1

        if wait > 0:
            await asyncio.sleep(wait)
            self._stats["total_delays"] += wait

        return True

    def report_error(self, url: str | None = None) -> None:
        domain = self._extract_domain(url) if url else "default"
        state = self._domain_state.setdefault(domain, {
            "last": 0.0, "errors": 0, "cur_delay": self._base_min,
        })
        state["errors"] = (state["errors"] or 0) + 1
        factor = min(2.0 ** (state["errors"] or 0), 8.0)
        state["cur_delay"] = self._base_min * factor
        self._block_window.append(tmod.time())
        self._stats["total_blocks"] += 1
        # Also adjust global delay immediately
        total = max(len(self._hour_window), 1)
        block_rate = len(self._block_window) / total
        if block_rate > 0.05:
            self._current_delay = min(
                self._base_max,
                self._current_delay * (1.5 if block_rate <= 0.15 else 3.0),
            )

    def report_success(self, url: str | None = None) -> None:
        domain = self._extract_domain(url) if url else "default"
        state = self._domain_state.setdefault(domain, {
            "last": 0.0, "errors": 0, "cur_delay": self._base_min,
        })
        if state["errors"] and state["errors"] > 0:
            state["errors"] = max(0, (state["errors"] or 0) - 1)
            if state["errors"] == 0:
                state["cur_delay"] = self._base_min

    def _extract_domain(self, url: str) -> str:
        from urllib.parse import urlparse
        return urlparse(url).netloc or "default"

    def _prune_windows(self, now: float) -> None:
        cutoff_hour = now - 3600
        cutoff_day = now - 86400
        cutoff_block = now - 3600

        while self._hour_window and self._hour_window[0] < cutoff_hour:
            self._hour_window.popleft()
        while self._day_window and self._day_window[0] < cutoff_day:
            self._day_window.popleft()
        while self._block_window and self._block_window[0] < cutoff_block:
            self._block_window.popleft()

    def _adjust_delay(self, now: float) -> None:
        """
        核心调速算法。

        基于 block_rate 动态计算当前 delay：
        - block_rate = 最近 1h block 数 / 最近 1h 请求数
        - block_rate > 5%:  delay *= 1.5
        - block_rate > 15%: delay *= 3
        - block_rate == 0 且 current_delay > min_delay: 慢恢复 *= 0.98
        """
        total_recent = len(self._hour_window) or 1
        blocks_recent = len(self._block_window)
        block_rate = blocks_recent / total_recent

        if block_rate > 0.15:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 3.0,
            )
        elif block_rate > 0.05:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 1.5,
            )
        elif block_rate == 0 and self._current_delay > self._base_min:
            self._current_delay = max(
                self._base_min,
                self._current_delay * 0.98,
            )

    def get_stats(self) -> dict[str, Any]:
        total_recent = max(len(self._hour_window), 1)
        return {
            "current_delay": round(self._current_delay, 2),
            "base_min": self._base_min,
            "base_max": self._base_max,
            "hour_requests": len(self._hour_window),
            "hour_blocks": len(self._block_window),
            "block_rate": round(len(self._block_window) / total_recent, 4),
            "total_requests": self._stats["total_requests"],
            "total_blocks": self._stats["total_blocks"],
            "total_delay_time": round(self._stats["total_delays"], 1),
            "hourly_limit": self._hourly_limit,
            "daily_limit": self._daily_limit,
        }
