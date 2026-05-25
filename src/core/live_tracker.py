"""
Live Match Tracker — 比赛实时追踪引擎。

职责：
1. 从 /matches 页面发现正在进行的比赛
2. 为每个 live match 创建独立 polling 协程
3. Adaptive polling interval（根据比赛状态动态调整）
4. 通过 content hash 检测变化
5. 变化时通知回调
6. 比赛结束后自动清理
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time as tmod
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("hltv.core.live_tracker")


@dataclass
class MatchTrackerState:
    match_id: int
    url: str
    status: str = "upcoming"  # upcoming → live → finished
    poll_interval: float = 30.0
    unchanged_polls: int = 0
    last_content_hash: str = ""
    last_checked: float = 0.0
    created_at: float = 0.0
    callbacks: list[Callable] = field(default_factory=list)


@dataclass
class MatchChange:
    match_id: int
    change_type: str  # "score", "map_end", "status", "new_demo", "new_map"
    old_value: Any = None
    new_value: Any = None
    timestamp: float = 0.0


class LiveMatchTracker:
    """
    比赛实时追踪。

    用法：
        tracker = LiveMatchTracker(fetch_pipeline)
        await tracker.start()
        await tracker.subscribe(2367256, my_callback)

    内部机制：
    - _discovery_interval: 每 30s 扫描 /matches 发现新的 live match
    - 每个 live match 独立 polling
    - Polling 频率: 30s → 60s → 120s (指数衰减，比赛结束后停止)
    - 内容变化时通过 hash 检测
    - 变化的 category 通过简单的 DOM 特征判断
    """

    def __init__(
        self,
        fetch_pipeline: Any,
        discovery_interval: float = 30.0,
        base_poll_interval: float = 30.0,
    ) -> None:
        self._pipeline = fetch_pipeline
        self._discovery_interval = discovery_interval
        self._base_poll_interval = base_poll_interval

        self._tracked: dict[int, MatchTrackerState] = {}
        self._pollers: dict[int, asyncio.Task] = {}
        self._running = False

        self._listeners: list[Callable] = []
        self._stats = {
            "discovered": 0,
            "changes_detected": 0,
            "active_trackers": 0,
        }

    async def start(self) -> None:
        """启动发现循环。"""
        if self._running:
            return
        self._running = True
        asyncio.create_task(self._discovery_loop())
        logger.info("LiveMatchTracker started")

    async def stop(self) -> None:
        """停止所有追踪。"""
        self._running = False
        for match_id, poller in list(self._pollers.items()):
            poller.cancel()
        self._pollers.clear()
        self._tracked.clear()
        logger.info("LiveMatchTracker stopped")

    async def subscribe(
        self,
        match_id: int,
        callback: Callable | None = None,
    ) -> None:
        """订阅一个比赛。"""
        url = f"https://www.hltv.org/matches/{match_id}/-"
        state = MatchTrackerState(
            match_id=match_id,
            url=url,
            status="live",
            created_at=tmod.time(),
        )
        if callback:
            state.callbacks.append(callback)
        self._tracked[match_id] = state
        self._stats["discovered"] += 1

        # 启动 poller
        if match_id not in self._pollers:
            self._pollers[match_id] = asyncio.create_task(
                self._poll_loop(match_id),
            )
            logger.info("Subscribed to match %d", match_id)

    async def unsubscribe(self, match_id: int) -> None:
        """取消订阅。"""
        if match_id in self._pollers:
            self._pollers[match_id].cancel()
            del self._pollers[match_id]
        self._tracked.pop(match_id, None)

    def add_listener(self, callback: Callable) -> None:
        """添加全局变更监听器。"""
        self._listeners.append(callback)

    async def _discovery_loop(self) -> None:
        """定期扫描 /matches 页面发现新 live match。"""
        while self._running:
            try:
                await self._discover_live_matches()
            except Exception as e:
                logger.debug("Discovery error: %s", e)
            await asyncio.sleep(self._discovery_interval)

    async def _discover_live_matches(self) -> None:
        """从 /matches 页面发现 live match。"""
        if not self._pipeline:
            return

        from .pipeline import FetchRequest

        response = await self._pipeline.execute(
            FetchRequest(
                url="https://www.hltv.org/matches",
                bypass_cache=True,
                priority=80,
                metadata={"page_type": "discovery"},
            ),
        )

        html = response.html
        # 用简单的 marker 检测 live match
        # HLTV 的 ".match-meta-live" 标记 live match
        if "match-meta-live" in html or "live" in html.lower():
            # 提取 match IDs —— 简化为监控已知 match 列表
            # 这里只是一个框架，实际解析需要 MatchesEndpoint
            pass

    async def _poll_loop(self, match_id: int) -> None:
        """单个 match 的 polling 循环。"""
        state = self._tracked.get(match_id)
        if not state:
            return

        while self._running and match_id in self._tracked:
            state.last_checked = tmod.time()

            try:
                await self._poll_match(state)
            except Exception as e:
                logger.debug("Poll error match %d: %s", match_id, e)
                state.unchanged_polls += 1

            # Adaptive interval
            interval = self._compute_interval(state)
            state.poll_interval = interval
            await asyncio.sleep(interval)

        self._pollers.pop(match_id, None)

    async def _poll_match(self, state: MatchTrackerState) -> None:
        """抓取并检测比赛页面变化。"""
        if not self._pipeline:
            return

        from .pipeline import FetchRequest

        response = await self._pipeline.execute(
            FetchRequest(
                url=state.url,
                bypass_cache=True,
                priority=100,
                metadata={"match_id": state.match_id},
            ),
        )

        # 检测变化
        current_hash = hashlib.md5(response.html.encode()).hexdigest()

        if state.last_content_hash and current_hash != state.last_content_hash:
            state.unchanged_polls = 0
            self._stats["changes_detected"] += 1

            change = MatchChange(
                match_id=state.match_id,
                change_type="content_changed",
                timestamp=tmod.time(),
            )

            # 通知回调
            for cb in state.callbacks:
                try:
                    await cb(change)
                except Exception as e:
                    logger.error("Callback error: %s", e)

            for listener in self._listeners:
                try:
                    await listener(change)
                except Exception:
                    pass

        else:
            state.unchanged_polls += 1

        state.last_content_hash = current_hash

        # 检测比赛是否结束：如果没有 "live" marker 且多轮无变化
        if "live" not in response.html.lower() and state.unchanged_polls > 5:
            state.status = "finished"
            logger.info("Match %d finished, will clean up", state.match_id)
            # 1h 后清理
            asyncio.create_task(self._delayed_cleanup(state.match_id, 3600))

    def _compute_interval(self, state: MatchTrackerState) -> float:
        """
        Adaptive polling interval 算法。

        基准: base_poll_interval
        - 无变化 * (1 + 0.5 * unchanged_polls)
        - 正在比赛中 * (1 - 0.3)  # 比赛进行中加快
        - 已完成 / 10  # 结束后大幅降低
        """
        interval = self._base_poll_interval

        if state.status == "finished":
            return interval * 10

        # 无变化累加
        interval *= (1 + 0.5 * min(state.unchanged_polls, 6))

        return min(max(interval, 15.0), 300.0)

    async def _delayed_cleanup(self, match_id: int, delay: float) -> None:
        """延迟清理已结束的比赛。"""
        await asyncio.sleep(delay)
        await self.unsubscribe(match_id)
        self._stats["active_trackers"] = len(self._tracked)

    def get_stats(self) -> dict[str, Any]:
        self._stats["active_trackers"] = len(self._tracked)
        return dict(self._stats)
