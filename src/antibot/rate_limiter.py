from __future__ import annotations

import asyncio
import random
import time as tmod
from collections import deque
from typing import Any


class AdaptiveRateLimiter:
    """
    基于滑动时间窗口的智能速率限制器 v2。

    核心升级：
    1. 响应时间感知调速 —— 慢响应 = 可能被限速，自动降速
    2. 预测式调速 —— 基于历史 block 频率预测未来风险，提前降速
    3. 渐进恢复 —— block 消失后不立即恢复，而是逐步试探性恢复
    4. 路径级限速 —— 不同路径独立限速（详情页 vs 列表页）
    5. 自适应窗口 —— 根据当前风险等级动态调整观测窗口
    6. 紧急制动 —— 连续 block 时快速进入冷却期
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

        self._hour_window: deque[float] = deque()
        self._day_window: deque[float] = deque()
        self._block_window: deque[float] = deque()

        self._domain_state: dict[str, dict[str, Any]] = {}

        self._response_times: deque[float] = deque(maxlen=50)
        self._baseline_response_time: float = 2.0

        self._cooldown_until: float = 0.0
        self._consecutive_blocks: int = 0

        self._recovery_state: str = "normal"
        self._recovery_start: float = 0.0
        self._recovery_target: float = min_delay
        self._recovery_step: int = 0
        self._recovery_steps_total: int = 10

        self._path_state: dict[str, dict[str, Any]] = {}

        self._lock = asyncio.Lock()
        self._stats = {
            "total_requests": 0,
            "total_blocks": 0,
            "total_delays": 0.0,
            "cooldown_activations": 0,
            "recovery_cycles": 0,
        }

    async def acquire(self, url: str | None = None) -> bool:
        domain = self._extract_domain(url) if url else "default"
        now = tmod.time()
        cooldown_wait = 0.0

        async with self._lock:
            self._prune_windows(now)

            if self._hourly_limit > 0 and len(self._hour_window) >= self._hourly_limit:
                return False
            if self._daily_limit > 0 and len(self._day_window) >= self._daily_limit:
                return False

            if now < self._cooldown_until:
                cooldown_wait = self._cooldown_until - now

            self._adjust_delay(now)

            state = self._domain_state.setdefault(domain, {
                "last": 0.0, "errors": 0, "cur_delay": self._base_min,
                "response_times": deque(maxlen=20),
            })
            elapsed = now - (state["last"] or 0)
            cur_delay: float = state["cur_delay"] or self._base_min

            path_delay = self._get_path_delay(url)
            effective_delay = max(cur_delay, path_delay)

            wait = max(0.0, effective_delay - elapsed)

            if self._jitter and wait > 0:
                spread = effective_delay * 0.2
                wait = max(0.0, wait + random.gauss(0, spread))

            state["last"] = tmod.time()
            self._hour_window.append(now)
            self._day_window.append(now)
            self._stats["total_requests"] += 1

        if cooldown_wait > 0:
            await asyncio.sleep(cooldown_wait)

        if wait > 0:
            await asyncio.sleep(wait)
            self._stats["total_delays"] += wait

        return True

    async def report_error(self, url: str | None = None) -> None:
        async with self._lock:
            domain = self._extract_domain(url) if url else "default"
            state = self._domain_state.setdefault(domain, {
                "last": 0.0, "errors": 0, "cur_delay": self._base_min,
                "response_times": deque(maxlen=20),
            })
            state["errors"] = (state["errors"] or 0) + 1
            self._consecutive_blocks += 1

            factor = min(2.0 ** (state["errors"] or 0), 8.0)
            state["cur_delay"] = self._base_min * factor

            self._block_window.append(tmod.time())
            self._stats["total_blocks"] += 1

            if self._consecutive_blocks >= 3:
                cooldown_duration = min(30.0 * (2 ** (self._consecutive_blocks - 3)), 300.0)
                self._cooldown_until = tmod.time() + cooldown_duration
                self._stats["cooldown_activations"] += 1

            self._update_path_state(url, blocked=True)

            self._recovery_state = "blocked"
            self._recovery_start = 0

            total = max(len(self._hour_window), 1)
            block_rate = len(self._block_window) / total
            if block_rate > 0.05:
                self._current_delay = min(
                    self._base_max,
                    self._current_delay * (1.5 if block_rate <= 0.15 else 3.0),
                )

    async def report_success(self, url: str | None = None, response_time: float = 0.0) -> None:
        async with self._lock:
            domain = self._extract_domain(url) if url else "default"
            state = self._domain_state.setdefault(domain, {
                "last": 0.0, "errors": 0, "cur_delay": self._base_min,
                "response_times": deque(maxlen=20),
            })

            if response_time > 0:
                self._response_times.append(response_time)
                if isinstance(state.get("response_times"), deque):
                    state["response_times"].append(response_time)
                self._update_baseline_response_time()

            self._consecutive_blocks = max(0, self._consecutive_blocks - 1)

            if state["errors"] and state["errors"] > 0:
                state["errors"] = max(0, (state["errors"] or 0) - 1)
                if state["errors"] == 0:
                    if self._recovery_state != "recovering":
                        self._recovery_state = "recovering"
                        self._recovery_start = tmod.time()
                        self._recovery_target = self._base_min
                        self._recovery_step = 0
                        self._stats["recovery_cycles"] += 1

            self._update_path_state(url, blocked=False)

    def _update_baseline_response_time(self) -> None:
        if len(self._response_times) < 5:
            return
        sorted_times = sorted(self._response_times)
        trim = len(sorted_times) // 4
        if trim > 0:
            trimmed = sorted_times[trim:-trim]
        else:
            trimmed = sorted_times
        if trimmed:
            self._baseline_response_time = sum(trimmed) / len(trimmed)

    def _adjust_delay(self, now: float) -> None:
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
            self._apply_recovery(now)

        self._adjust_for_response_time()

        self._predictive_adjust(now)

    def _apply_recovery(self, now: float) -> None:
        if self._recovery_state == "recovering":
            elapsed = now - self._recovery_start
            step_duration = 30.0
            expected_step = int(elapsed / step_duration)

            if expected_step > self._recovery_step:
                self._recovery_step = min(expected_step, self._recovery_steps_total)
                progress = self._recovery_step / self._recovery_steps_total
                eased = 1 - (1 - progress) ** 2
                self._current_delay = self._current_delay - (
                    self._current_delay - self._recovery_target
                ) * eased * 0.15
                self._current_delay = max(self._base_min, self._current_delay)

                if self._recovery_step >= self._recovery_steps_total:
                    self._current_delay = self._base_min
                    self._recovery_state = "normal"
        elif self._recovery_state == "normal":
            self._current_delay = max(
                self._base_min,
                self._current_delay * 0.97,
            )

    def _adjust_for_response_time(self) -> None:
        if len(self._response_times) < 5:
            return

        recent = list(self._response_times)[-10:]
        avg_recent = sum(recent) / len(recent)

        if avg_recent > self._baseline_response_time * 2.0:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 1.2,
            )
        elif avg_recent > self._baseline_response_time * 1.5:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 1.05,
            )

    def _predictive_adjust(self, now: float) -> None:
        if len(self._block_window) < 3:
            return

        recent_blocks = [t for t in self._block_window if now - t < 1800]
        if len(recent_blocks) < 2:
            return

        intervals = []
        for i in range(1, len(recent_blocks)):
            intervals.append(recent_blocks[i] - recent_blocks[i - 1])

        if not intervals:
            return

        avg_interval = sum(intervals) / len(intervals)
        if avg_interval < 60:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 1.3,
            )
        elif avg_interval < 120:
            self._current_delay = min(
                self._base_max,
                self._current_delay * 1.1,
            )

    def _get_path_delay(self, url: str | None = None) -> float:
        if not url:
            return 0.0
        from urllib.parse import urlparse
        path = urlparse(url).path
        ps = self._path_state.get(path)
        if not ps:
            return 0.0
        if ps.get("blocked_recently"):
            return self._base_min * 2.0
        return 0.0

    def _update_path_state(self, url: str | None, blocked: bool) -> None:
        if not url:
            return
        from urllib.parse import urlparse
        path = urlparse(url).path
        ps = self._path_state.setdefault(path, {
            "errors": 0, "successes": 0, "blocked_recently": False, "last_block": 0.0,
        })
        if blocked:
            ps["errors"] = ps.get("errors", 0) + 1
            ps["blocked_recently"] = True
            ps["last_block"] = tmod.time()
        else:
            ps["successes"] = ps.get("successes", 0) + 1
            if tmod.time() - ps.get("last_block", 0) > 300:
                ps["blocked_recently"] = False

        if len(self._path_state) > 500:
            cutoff = tmod.time() - 3600
            self._path_state = {
                k: v for k, v in self._path_state.items()
                if v.get("last_block", 0) > cutoff or v.get("successes", 0) > 0
            }

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
            "recovery_state": self._recovery_state,
            "recovery_step": f"{self._recovery_step}/{self._recovery_steps_total}",
            "consecutive_blocks": self._consecutive_blocks,
            "cooldown_active": tmod.time() < self._cooldown_until,
            "baseline_response_time": round(self._baseline_response_time, 2),
            "path_states": len(self._path_state),
            "cooldown_activations": self._stats["cooldown_activations"],
        }
