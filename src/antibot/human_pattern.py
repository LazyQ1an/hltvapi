from __future__ import annotations

import random
import time as tmod
from typing import Any


class HumanRequestPattern:
    """
    模拟真实用户访问模式的请求间隔生成器。

    核心思想：真实用户不会均匀间隔发请求。

    Burst 模式：
    - 浏览期: 快速连续访问 3-8 个页面，间隔 1-3s
    - 阅读期: 30-90s 停顿（看比赛、读文章）

    每日模式：
    - 活跃时段 (8:00-23:00): 80% 的请求
    - 休息时段 (23:00-8:00): 20% 的请求

    额外随机：
    - 每 20-40 个请求"误点"一次（跳过 1 个 URL）
    - 随机回头访问之前看过的页面（增加真实性）
    """

    def __init__(
        self,
        burst_min: int = 3,
        burst_max: int = 8,
        burst_delay_min: float = 1.0,
        burst_delay_max: float = 3.0,
        rest_delay_min: float = 30.0,
        rest_delay_max: float = 90.0,
        active_hour_start: int = 8,
        active_hour_end: int = 23,
    ) -> None:
        self._burst_min = burst_min
        self._burst_max = burst_max
        self._burst_delay_min = burst_delay_min
        self._burst_delay_max = burst_delay_max
        self._rest_delay_min = rest_delay_min
        self._rest_delay_max = rest_delay_max
        self._active_start = active_hour_start
        self._active_end = active_hour_end

        self._requests_in_burst = 0
        self._current_burst_size = random.randint(burst_min, burst_max)
        self._total_requests = 0
        self._reset_time = tmod.time()

        # 用于"回头访问"模拟
        self._recent_urls: list[str] = []

    async def next_delay(self, url: str | None = None) -> float:
        """
        计算下一次请求的等待时间。

        根据 burst/rest 状态和当天时段返回不同的间隔。
        """
        self._total_requests += 1

        if self._requests_in_burst >= self._current_burst_size:
            self._requests_in_burst = 0
            self._current_burst_size = random.randint(
                self._burst_min, self._burst_max,
            )
            delay = self._get_rest_delay()
        else:
            self._requests_in_burst += 1
            delay = self._get_burst_delay()

        # 根据时段缩放
        hour_factor = self._get_hour_factor()
        delay *= hour_factor

        # 每隔 20-40 请求随机多加一次"误点停顿"
        if self._total_requests % random.randint(20, 40) == 0:
            delay += random.uniform(5.0, 15.0)

        if url:
            self._recent_urls.append(url)
            if len(self._recent_urls) > 100:
                self._recent_urls.pop(0)

        return delay

    def _get_burst_delay(self) -> float:
        return random.uniform(self._burst_delay_min, self._burst_delay_max)

    def _get_rest_delay(self) -> float:
        return random.uniform(self._rest_delay_min, self._rest_delay_max)

    def _get_hour_factor(self) -> float:
        """根据当前时段返回缩放因子。活跃时段 1.0，休息时段 2.0-5.0。"""
        hour = tmod.localtime().tm_hour
        if self._active_start <= hour < self._active_end:
            return 1.0
        return random.uniform(2.0, 5.0)

    def should_skip(self) -> bool:
        """模拟误点：随机跳过 1 个 URL。"""
        return random.random() < 0.03

    def get_reset_status(self) -> bool:
        """检查是否需要重置 burst 计数器（比如长时间空闲后）。"""
        if tmod.time() - self._reset_time > 600:
            self._requests_in_burst = self._current_burst_size
            self._reset_time = tmod.time()
            return True
        return False

    def get_stats(self) -> dict[str, Any]:
        return {
            "burst_position": f"{self._requests_in_burst}/{self._current_burst_size}",
            "total_requests": self._total_requests,
            "recent_urls": len(self._recent_urls),
            "current_hour_factor": self._get_hour_factor(),
        }
