from __future__ import annotations

import logging
import random
import time as tmod
from typing import Any

from ..base import TransportSession
from ..identity import SessionIdentity

logger = logging.getLogger("hltv.transport.httpx_pool")


class HttpxSessionPool:
    """
    httpx AsyncClient 池。

    httpx 作为 fallback 传输层，在 curl_cffi 不可用或异常时使用。
    HTTP/2 支持通过 h2 库启用。
    """

    def __init__(
        self,
        size: int = 3,
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
        identity = SessionIdentity.random("win32")
        return TransportSession(transport="httpx", identity=identity)

    async def _init_client(self, session: TransportSession) -> None:
        try:
            import httpx

            proxy_url = self._resolve_proxy()
            limits = httpx.Limits(
                max_keepalive_connections=10,
                max_connections=50,
                keepalive_expiry=5.0,
            )

            http2 = False
            try:
                import h2  # noqa: F401
                http2 = True
            except ImportError:
                pass

            transport_kw: dict[str, Any] = {"limits": limits}
            if proxy_url:
                transport_kw["proxy"] = proxy_url

            session.client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self._config.client.timeout if self._config else 30,
                ),
                follow_redirects=True,
                http2=http2,
                **transport_kw,
            )
        except ImportError:
            logger.warning("httpx not available")
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

        candidates = [s for s in self.sessions if not s.banned and s.client is not None and s.health_score > 0]
        if not candidates:
            now = tmod.time()
            for s in self.sessions:
                if s.banned and s.ban_time and (now - s.ban_time) > 300:
                    s.unban()
                    candidates.append(s)
        if not candidates:
            return None

        scores = [s.health_score * (1 + random.uniform(0, 0.1)) for s in candidates]
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
        new_sessions = []
        for s in self.sessions:
            if s.is_expired and s.health_score < 0.3:
                new_sessions.append(self._create_session())
            else:
                new_sessions.append(s)
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

    async def close(self) -> None:
        for s in self.sessions:
            if s.client is not None:
                try:
                    await s.client.aclose()
                except Exception:
                    pass
