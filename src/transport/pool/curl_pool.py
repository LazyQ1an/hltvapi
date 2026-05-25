from __future__ import annotations

import logging
import random
import time as tmod
from typing import Any

from ..base import TransportSession
from ..identity import SessionIdentity

logger = logging.getLogger("hltv.transport.curl_pool")


class CurlSessionPool:
    """
    curl_cffi session 池。

    管理多个 curl_cffi AsyncSession，每个有独立的 TLS 指纹和 cookie。
    """

    def __init__(
        self,
        size: int = 10,
        fingerprint_mgr: Any = None,
        config: Any = None,
    ) -> None:
        self.size = size
        self._fingerprint_mgr = fingerprint_mgr
        self._config = config
        self.sessions: list[TransportSession] = []
        self._initialized = False

    async def _ensure_init(self) -> None:
        if self._initialized:
            return
        for _ in range(self.size):
            session = self._create_session()
            await self._init_client(session)
            self.sessions.append(session)
        self._initialized = True

    def _create_session(self) -> TransportSession:
        platform = random.choice(["win32", "darwin", "linux"])
        identity = SessionIdentity.random(platform)
        if self._fingerprint_mgr:
            identity.impersonate_version = self._fingerprint_mgr.assign()
        return TransportSession(transport="curl", identity=identity)

    async def _init_client(self, session: TransportSession) -> None:
        try:
            from curl_cffi import requests as curl_requests

            proxy_url = self._resolve_proxy()
            session_kw: dict[str, Any] = {
                "impersonate": session.identity.impersonate_version,
                "timeout": (self._config.client.timeout if self._config else 30),
            }
            if proxy_url:
                session_kw["proxies"] = {"https": proxy_url, "http": proxy_url}
            session.client = curl_requests.AsyncSession(**session_kw)
        except ImportError:
            logger.warning("curl_cffi not available")
            session.health_score = 0.0

    def _resolve_proxy(self) -> str | None:
        try:
            if self._config and hasattr(self._config, "proxy"):
                return str(self._config.proxy) if self._config.proxy else None
        except Exception:
            pass
        import os
        for env_var in ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"]:
            val = os.environ.get(env_var)
            if val:
                return val
        return None

    async def acquire(self) -> TransportSession | None:
        await self._ensure_init()
        if not self.sessions:
            return None

        # Softmax 概率选择（基于 health_score + 随机噪声）
        candidates = [s for s in self.sessions if not s.banned and s.client is not None and s.health_score > 0]
        if not candidates:
            # 尝试 unban 过期的 session
            now = tmod.time()
            for s in self.sessions:
                if s.banned and s.ban_time and (now - s.ban_time) > 300:
                    s.unban()
                    candidates.append(s)
        if not candidates:
            return None

        scores = [
            s.health_score * (1 + random.uniform(0, 0.1))
            for s in candidates
        ]
        total = sum(scores)
        if total <= 0:
            return random.choice(candidates)
        normalized = [s / total for s in scores]
        r = random.random()
        cumulative = 0.0
        for i, p in enumerate(normalized):
            cumulative += p
            if r <= cumulative:
                return candidates[i]
        return candidates[-1]

    def release(self, session_id: str, success: bool) -> None:
        for s in self.sessions:
            if s.id == session_id:
                if success:
                    s.record_success()
                else:
                    s.record_block()
                break
        self._cleanup()

    def _cleanup(self) -> None:
        """回收过期 session，创建替代。"""
        new_sessions = []
        for s in self.sessions:
            if s.is_expired and s.health_score < 0.3:
                new_s = self._create_session()
                new_sessions.append(new_s)
            else:
                new_sessions.append(s)

        # 补充不足的数量
        while len(new_sessions) < self.size:
            new_sessions.append(self._create_session())

        self.sessions = new_sessions

    def has_available(self) -> bool:
        if not self._initialized:
            return True
        return any(
            s.client is not None and not s.banned and s.health_score > 0
            for s in self.sessions
        )

    def available_count(self) -> int:
        if not self._initialized:
            return self.size
        return sum(1 for s in self.sessions if not s.banned and s.client is not None)

    def banned_count(self) -> int:
        return sum(1 for s in self.sessions if s.banned)

    async def close(self) -> None:
        for s in self.sessions:
            if s.client is not None:
                try:
                    await s.client.close()
                except Exception:
                    pass
