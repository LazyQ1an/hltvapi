from __future__ import annotations

import time as tmod
import uuid
from typing import Any, Literal

from .identity import SessionIdentity


class TransportSession:
    """
    单个传输层 session 的包装。

    每个 TransportSession 代表一个独立的"用户会话"：
    - 独立的身份指纹（UA / platform / viewport / ...）
    - 独立的 cookie jar
    - 独立的健康度评分
    - 独立的重试/block 计数器

    一个 SessionPool 管理多个 TransportSession 实例。
    """

    def __init__(
        self,
        transport: Literal["curl", "httpx", "playwright", "nodriver"],
        identity: SessionIdentity | None = None,
    ) -> None:
        self.id: str = uuid.uuid4().hex[:12]
        self.transport = transport
        self.identity = identity or SessionIdentity.random()
        self.client: Any = None
        self.cookie_jar: dict[str, str] = {}

        self.created_at = tmod.time()
        self.last_used = self.created_at
        self.request_count = 0
        self.block_count = 0
        self.consecutive_blocks = 0
        self.success_count = 0

        # 健康度 0.0 (死亡) ~ 1.0 (完美)
        self.health_score = 1.0

        # Optional anti-detection (set by transport pools)
        self._stealth_script: str | None = None
        self._behavior: dict[str, Any] = {}

        # 封禁状态
        self.banned = False
        self.ban_time: float | None = None

    def record_success(self) -> None:
        self.last_used = tmod.time()
        self.request_count += 1
        self.success_count += 1
        self.consecutive_blocks = 0
        self._recalc_health()

    def record_block(self) -> None:
        self.last_used = tmod.time()
        self.block_count += 1
        self.consecutive_blocks += 1
        if self.consecutive_blocks >= 3:
            self.banned = True
            self.ban_time = tmod.time()
        self._recalc_health()

    def unban(self) -> None:
        self.banned = False
        self.ban_time = None
        self.consecutive_blocks = 0
        self._recalc_health()

    def _recalc_health(self) -> None:
        total = self.success_count + self.block_count
        if total == 0:
            self.health_score = 1.0
            return

        success_rate = self.success_count / total
        age_hours = (tmod.time() - self.created_at) / 3600
        age_factor = min(1.0, age_hours / 24.0)  # 24h 后达最大信任度

        self.health_score = (
            0.6 * success_rate +
            0.2 * age_factor +
            0.2 * max(0, 1 - self.consecutive_blocks / 5)
        )

    @property
    def is_expired(self) -> bool:
        """session 是否已达最大请求数或寿命。"""
        max_requests = {"curl": 200, "httpx": 200, "playwright": 100, "nodriver": 80}
        max_age = 86400  # 24h
        return (
            self.request_count >= max_requests.get(self.transport, 200)
            or (tmod.time() - self.created_at) > max_age
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "transport": self.transport,
            "platform": self.identity.platform,
            "ua": self.identity.user_agent[:60],
            "created": round(self.created_at, 1),
            "requests": self.request_count,
            "success": self.success_count,
            "blocks": self.block_count,
            "consecutive_blocks": self.consecutive_blocks,
            "health": round(self.health_score, 2),
            "banned": self.banned,
            "expired": self.is_expired,
        }
