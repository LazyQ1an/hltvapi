"""
请求调度引擎：智能请求队列 + 优先级编排 + 路径连贯性。

核心目标：
1. 路径连贯性 —— 让同一 session 的请求看起来像真实用户在浏览
2. 优先级编排 —— 高优先级请求优先处理，低优先级填充间隙
3. 请求去重 —— 同一 URL 在短时间内不重复请求
4. 自适应并发 —— 根据当前 block 风险动态调整并发数
5. 请求批处理 —— 将相关请求组合成自然的浏览序列
"""

from __future__ import annotations

import asyncio
import heapq
import time as tmod
from dataclasses import dataclass, field
from typing import Any

from src.antibot.human_pattern import HumanRequestPattern
from src.utils.logger import get_logger

logger = get_logger("scheduler.engine")


@dataclass(order=True)
class ScheduledRequest:
    priority: int
    url: str = field(compare=False)
    cache_ttl: int | None = field(default=None, compare=False)
    cache_key: str | None = field(default=None, compare=False)
    force_playwright: bool = field(default=False, compare=False)
    prefer_curl: bool = field(default=False, compare=False)
    metadata: dict = field(default_factory=dict, compare=False)
    enqueued_at: float = field(default_factory=tmod.time, compare=False)
    page_type: str = field(default="home", compare=False)


class RequestScheduler:
    """
    智能请求调度引擎。

    工作方式：
    1. 将请求加入优先级队列
    2. 根据 HumanRequestPattern 的马尔可夫链建议下一个路径
    3. 优先选择与当前 session 浏览历史连贯的请求
    4. 根据当前风险等级调整并发数
    5. 批量调度时保持路径连贯性
    """

    def __init__(
        self,
        human_pattern: HumanRequestPattern | None = None,
        max_concurrency: int = 3,
        risk_threshold_high: float = 0.7,
        risk_threshold_low: float = 0.3,
    ) -> None:
        self._human_pattern = human_pattern or HumanRequestPattern()
        self._max_concurrency = max_concurrency
        self._risk_threshold_high = risk_threshold_high
        self._risk_threshold_low = risk_threshold_low

        self._queue: list[ScheduledRequest] = []
        self._in_flight: int = 0
        self._completed: int = 0
        self._failed: int = 0

        self._recent_urls: dict[str, float] = {}
        self._dedup_ttl = 300

        self._current_risk: float = 0.0
        self._last_path_type: str = "home"

        self._lock = asyncio.Lock()

    def enqueue(
        self,
        url: str,
        priority: int = 5,
        cache_ttl: int | None = None,
        cache_key: str | None = None,
        force_playwright: bool = False,
        prefer_curl: bool = False,
        metadata: dict | None = None,
    ) -> bool:
        """
        将请求加入调度队列。

        优先级：
        - 1-3: 高优先级（用户直接请求、实时数据）
        - 4-6: 中优先级（常规数据抓取）
        - 7-10: 低优先级（预取、后台更新）

        Returns:
            True if enqueued, False if duplicate.
        """
        now = tmod.time()

        if url in self._recent_urls:
            last_time = self._recent_urls[url]
            if now - last_time < self._dedup_ttl:
                return False

        page_type = self._classify_url(url)

        adjusted_priority = self._adjust_priority(priority, page_type)

        request = ScheduledRequest(
            priority=adjusted_priority,
            url=url,
            cache_ttl=cache_ttl,
            cache_key=cache_key,
            force_playwright=force_playwright,
            prefer_curl=prefer_curl,
            metadata=metadata or {},
            page_type=page_type,
        )

        heapq.heappush(self._queue, request)
        self._recent_urls[url] = now

        if len(self._recent_urls) > 1000:
            cutoff = now - self._dedup_ttl
            self._recent_urls = {
                k: v for k, v in self._recent_urls.items() if v > cutoff
            }

        return True

    def enqueue_batch(
        self,
        urls: list[str],
        priority: int = 5,
        **kwargs: Any,
    ) -> int:
        """
        批量加入请求，自动按路径连贯性排序。

        Returns:
            成功加入队列的请求数量。
        """
        sorted_urls = self._sort_by_coherence(urls)
        count = 0
        for url in sorted_urls:
            if self.enqueue(url, priority=priority, **kwargs):
                count += 1
        return count

    def dequeue(self) -> ScheduledRequest | None:
        """
        取出下一个应该执行的请求。

        选择策略：
        1. 如果有与当前路径连贯的请求，优先选择
        2. 否则按优先级选择
        3. 跳过最近已请求过的 URL
        """
        if not self._queue:
            return None

        suggested = self._human_pattern.suggest_next_path()

        coherent = None
        for req in self._queue:
            if req.page_type == suggested:
                coherent = req
                break

        if coherent is not None:
            self._queue.remove(coherent)
            heapq.heapify(self._queue)
            self._last_path_type = coherent.page_type
            self._in_flight += 1
            return coherent

        request = heapq.heappop(self._queue)
        self._last_path_type = request.page_type
        self._in_flight += 1
        return request

    def report_complete(self, url: str, success: bool) -> None:
        self._in_flight = max(0, self._in_flight - 1)
        if success:
            self._completed += 1
        else:
            self._failed += 1

    def update_risk(self, risk_level: float) -> None:
        self._current_risk = risk_level

    def get_effective_concurrency(self) -> int:
        """
        根据当前风险等级动态调整并发数。

        风险低 → 可以更多并发
        风险高 → 减少并发
        """
        if self._current_risk >= self._risk_threshold_high:
            return max(1, self._max_concurrency // 3)
        if self._current_risk >= self._risk_threshold_low:
            return max(1, self._max_concurrency // 2)
        return self._max_concurrency

    def _adjust_priority(self, base_priority: int, page_type: str) -> int:
        """
        根据路径连贯性调整优先级。

        如果请求的 page_type 与当前浏览路径一致，降低优先级数值（提高优先级）。
        """
        suggested = self._human_pattern.suggest_next_path()
        if page_type == suggested:
            return max(1, base_priority - 2)

        coherence_map = {
            "matches": {"match_detail": -1, "results": -1},
            "results": {"match_detail": -1, "matches": -1},
            "ranking": {"team_detail": -1, "stats": -1},
            "news": {"news_detail": -1},
            "events": {"event_detail": -1},
            "match_detail": {"team_detail": -1, "player_detail": -1},
            "team_detail": {"player_detail": -1, "matches": -1},
            "player_detail": {"team_detail": -1, "stats": -1},
        }

        related = coherence_map.get(self._last_path_type, {})
        if page_type in related:
            return max(1, base_priority + related[page_type])

        return base_priority

    def _sort_by_coherence(self, urls: list[str]) -> list[str]:
        """
        按浏览路径连贯性排序 URL。

        模拟真实用户的浏览顺序：
        列表页 → 详情页 → 关联页
        """
        type_order = {
            "home": 0,
            "matches": 1,
            "results": 1,
            "ranking": 1,
            "news": 1,
            "events": 1,
            "stats": 1,
            "match_detail": 2,
            "team_detail": 3,
            "player_detail": 3,
            "news_detail": 2,
            "event_detail": 2,
        }

        def sort_key(url: str) -> int:
            pt = self._classify_url(url)
            return type_order.get(pt, 5)

        return sorted(urls, key=sort_key)

    def _classify_url(self, url: str) -> str:
        path = url.lower()
        if "/matches/" in path and path.count("/") > 3:
            return "match_detail"
        if "/matches" in path:
            return "matches"
        if "/results/" in path and path.count("/") > 3:
            return "match_detail"
        if "/results" in path:
            return "results"
        if "/ranking" in path:
            return "ranking"
        if "/team/" in path:
            return "team_detail"
        if "/player/" in path:
            return "player_detail"
        if "/news/" in path and path.count("/") > 3:
            return "news_detail"
        if "/news" in path:
            return "news"
        if "/events/" in path and path.count("/") > 3:
            return "event_detail"
        if "/events" in path:
            return "events"
        if "/stats" in path:
            return "stats"
        return "home"

    def get_stats(self) -> dict[str, Any]:
        return {
            "queue_size": len(self._queue),
            "in_flight": self._in_flight,
            "completed": self._completed,
            "failed": self._failed,
            "current_risk": round(self._current_risk, 2),
            "effective_concurrency": self.get_effective_concurrency(),
            "last_path_type": self._last_path_type,
            "dedup_cache_size": len(self._recent_urls),
        }
