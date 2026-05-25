"""
Proxy Rotator — 代理轮换器。

设计原则：对于 HLTV，无代理（本地 IP）是首选。
代理仅作为紧急降级方案（本地 IP 被封时的过渡）。

策略：
- 本地 IP 为 baseline
- 代理仅做 fallback
- 每 N 次成功（N=5-15 随机）切换一次代理
- 记录每个代理的健康度和延迟
"""

from __future__ import annotations

import random
import time as tmod
from dataclasses import dataclass
from typing import Any


@dataclass
class Proxy:
    url: str
    proxy_type: str = "http"  # http | socks5 | socks5h
    region: str | None = None
    speed_ms: float = 0.0
    failed_count: int = 0
    success_count: int = 0
    consecutive_fails: int = 0
    health_score: float = 1.0
    banned: bool = False
    last_checked: float = 0.0

    def record_success(self, latency: float) -> None:
        self.success_count += 1
        self.consecutive_fails = 0
        if self.speed_ms == 0.0:
            self.speed_ms = latency
        else:
            self.speed_ms = self.speed_ms * 0.7 + latency * 0.3
        self.last_checked = tmod.time()
        self._recalc_health()

    def record_failure(self) -> None:
        self.failed_count += 1
        self.consecutive_fails += 1
        self.last_checked = tmod.time()
        if self.consecutive_fails >= 3:
            self.banned = True
        self._recalc_health()

    def _recalc_health(self) -> None:
        total = self.success_count + self.failed_count
        if total == 0:
            self.health_score = 1.0
            return
        success_rate = self.success_count / total
        fail_penalty = min(1.0, self.consecutive_fails / 5)
        speed_factor = max(0.5, min(1.0, 1.0 - self.speed_ms / 5000))
        self.health_score = 0.5 * success_rate + 0.3 * speed_factor + 0.2 * (1 - fail_penalty)


class ProxyRotator:
    """
    代理轮换器。

    初始状态：无代理（使用本地 IP）。
    当本地 IP 被封时，从代理池中选择最优代理。
    代理池可以通过文件或静态列表加载。
    """

    def __init__(self, proxies: list[Proxy] | None = None) -> None:
        self._proxies = proxies or []
        self._current_index = -1  # -1 = 使用本地 IP
        self._use_proxy = False
        self._requests_until_switch = random.randint(5, 15)

    def set_proxies(self, proxies: list[Proxy]) -> None:
        self._proxies = proxies

    def load_from_file(self, path: str) -> int:
        """从文件加载代理列表（每行一个 URL）。"""
        count = 0
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self._proxies.append(Proxy(url=line))
                        count += 1
        except Exception as e:
            raise ValueError(f"Failed to load proxies from {path}: {e}")
        return count

    async def get_proxy(self) -> Proxy | None:
        """
        获取当前最佳代理。

        Returns:
            Proxy 或 None（使用本地 IP）
        """
        if not self._proxies:
            return None

        if not self._use_proxy:
            return None

        # 每 N 次切换
        if self._requests_until_switch <= 0:
            self._requests_until_switch = random.randint(5, 15)
            self._use_proxy = True

        self._requests_until_switch -= 1

        # 选出健康度最高的代理
        candidates = [p for p in self._proxies if not p.banned]
        if not candidates:
            return None

        candidates.sort(key=lambda p: p.health_score, reverse=True)
        return candidates[0]

    async def report_result(
        self,
        proxy: Proxy | None,
        success: bool,
        latency: float,
    ) -> None:
        if proxy is None:
            return
        if success:
            proxy.record_success(latency)
            self._use_proxy = True
        else:
            proxy.record_failure()
            if proxy.banned:
                # 切换回本地 IP 或换代理
                self._use_proxy = not all(p.banned for p in self._proxies)

    def enable_proxy_mode(self) -> None:
        """切换到代理模式。"""
        self._use_proxy = True

    def disable_proxy_mode(self) -> None:
        """切回本地 IP 模式。"""
        self._use_proxy = False

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_proxies": len(self._proxies),
            "banned": sum(1 for p in self._proxies if p.banned),
            "healthy": sum(1 for p in self._proxies if not p.banned),
            "using_proxy": self._use_proxy,
            "current_index": self._current_index,
            "proxies": [
                {
                    "url": p.url,
                    "type": p.proxy_type,
                    "speed_ms": round(p.speed_ms, 1),
                    "health": round(p.health_score, 2),
                    "banned": p.banned,
                    "success": p.success_count,
                    "failed": p.failed_count,
                }
                for p in self._proxies
            ],
        }
