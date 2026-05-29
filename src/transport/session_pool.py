from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from .base import TransportSession
from .fingerprint import TLSFingerprintManager
from .pool.curl_pool import CurlSessionPool
from .pool.httpx_pool import HttpxSessionPool
from .pool.playwright_pool import PlaywrightContextPool
from .pool.nodriver_pool import NodriverContextPool

logger = logging.getLogger("hltv.transport.session_pool")


class SessionPool:
    """
    Multi-session pool manager.

    Core responsibilities:
    1. Maintain multiple TransportSessions, each with independent fingerprint + cookies
    2. Select best session by health_score
    3. Auto-create new sessions, recycle dead/expired ones
    4. Banned sessions isolated; don't affect other sessions

    Architecture:
    - curl pool: 10-15 sessions, each with independent TLS fingerprint
    - httpx pool: 3-5 sessions (fallback)
    - Playwright pool: 1-2 contexts (optional, stealth)

    Selection strategy:
    - Pick highest health_score session from pool each time
    - Add random noise to prevent starvation
    - 3 consecutive failures -> ban -> 5min unban
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

        # Transport-specific pools
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
        self._nodriver_pool = NodriverContextPool(
            size=playwright_count,
            config=config,
        )

        self._lock = asyncio.Lock()

    async def acquire(
        self,
        transport: Literal["curl", "httpx", "playwright", "nodriver"] = "curl",
    ) -> TransportSession:
        """
        Acquire a transport session.

        Args:
            transport: Transport layer type.

        Returns:
            Highest health_score session.

        Raises:
            RuntimeError: If no sessions are available.
        """
        pool = self._get_pool(transport)
        session = await pool.acquire()
        if session is None:
            raise RuntimeError(
                f"No available {transport} sessions (all banned or expired)",
            )
        return session

    def release(self, session_id: str, success: bool = True) -> None:
        """Release a session (called by FetchPipeline)."""
        for pool in self._pools:
            pool.release(session_id, success)

    _SAFE_SHARE_COOKIES = {"cf_clearance", "CookieConsent"}

    def share_cookies(self, cookies: dict[str, str], source_transport: str = "playwright") -> None:
        """Share safe cookies from one transport to others (e.g. cf_clearance from PW to curl)."""
        safe_cookies = {
            k: v for k, v in cookies.items()
            if k in self._SAFE_SHARE_COOKIES
        }
        if not safe_cookies:
            return
        for pool in self._pools:
            for s in pool.sessions:
                if s.transport != source_transport:
                    s.cookie_jar.update(safe_cookies)
    # --- Cookie persistence (disk-backed session jars) ---

    async def save_cookies(self) -> None:
        """Save all session cookie jars to disk for cross-restart persistence."""
        import json
        from pathlib import Path
        jar_dir = Path(".cache/hltv/session_cookies")
        jar_dir.mkdir(parents=True, exist_ok=True)
        for pool in self._pools:
            for s in pool.sessions:
                if s.cookie_jar:
                    fpath = jar_dir / f"{s.id}.json"
                    payload = {
                        "transport": s.transport,
                        "identity_fingerprint": s.identity.impersonate_version,
                        "cookies": s.cookie_jar,
                        "saved_at": __import__("time").time(),
                    }
                    fpath.write_text(json.dumps(payload, indent=2))

    def load_cookies(self) -> int:
        """Load previously saved cookie jars. Returns count of loaded sessions."""
        import json
        from pathlib import Path
        jar_dir = Path(".cache/hltv/session_cookies")
        if not jar_dir.exists():
            return 0
        loaded = 0
        for pool in self._pools:
            for s in pool.sessions:
                fpath = jar_dir / f"{s.id}.json"
                if fpath.exists():
                    try:
                        data = json.loads(fpath.read_text())
                        if data.get("transport") == s.transport:
                            s.cookie_jar.update(data.get("cookies", {}))
                            loaded += 1
                    except Exception:
                        pass
        if loaded:
            logger.info("Loaded %d saved cookie jars", loaded)
        return loaded

    async def close(self) -> None:
        """Close all transport connections."""
        for pool in self._pools:
            await pool.close()

    async def warmup(self) -> dict[str, Any]:
        """
        Warm up the Playwright pool: resolve CF challenge upfront and harvest cookies.

        Called at system startup to avoid first-request CF challenge latency.
        """
        result: dict[str, Any] = {"playwright_initialized": False, "cf_clearance": False}

        try:
            session = await self._playwright_pool.acquire()
            if session is None:
                return result

            result["playwright_initialized"] = True
            context = session.client
            page = await context.new_page()

            stealth = """
                Object.defineProperties(navigator, {
                    webdriver: { get: () => false },
                    plugins: { get: () => [1, 2, 3, 4, 5] },
                    languages: { get: () => ['en-US', 'en'] },
                });
                window.chrome = { runtime: {} };
            """
            await page.add_init_script(stealth)

            try:
                await page.goto("https://www.hltv.org/", wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass

            for _ in range(30):
                content = await page.content()
                content_lower = content.lower()
                has_hltv = any(
                    marker.lower() in content_lower
                    for marker in ["hltv", "nav-bar", "standard-box", "topnav"]
                )
                if has_hltv:
                    break
                await asyncio.sleep(1.0)

            try:
                cookies = await context.cookies("https://www.hltv.org")
                for c in cookies:
                    session.cookie_jar[c["name"]] = c["value"]
                    if c["name"] == "cf_clearance":
                        result["cf_clearance"] = True
            except Exception:
                pass

            await page.close()
            self._playwright_pool.release(session.id, success=True)

            if session.cookie_jar:
                self.share_cookies(session.cookie_jar, "playwright")

            logger.info("Playwright warmup complete: cf_clearance=%s", result["cf_clearance"])
        except Exception as e:
            logger.warning("Playwright warmup failed: %s", e)

        return result

    @property
    def _pools(self) -> list:
        return [self._curl_pool, self._httpx_pool, self._playwright_pool, self._nodriver_pool]

    def _get_pool(self, transport: str):
        if transport == "curl":
            return self._curl_pool
        elif transport == "httpx":
            return self._httpx_pool
        elif transport == "playwright":
            return self._playwright_pool
        elif transport == "nodriver":
            return self._nodriver_pool
        raise ValueError(f"Unknown transport: {transport}")

    def best_transport(self, url: str, stealth_mode: bool = False) -> str:
        """
        Determine the best transport layer for a request.

        Strategy:
        1. If curl has available sessions and isn't banned -> curl (fastest)
        2. If curl is all banned -> httpx
        3. If stealth mode and nothing available -> playwright
        4. When coming back down from playwright, try curl first

        Note: has_available() returns True before pool init (optimistic),
        so we check actual availability via available_count() when init is done.
        """
        curl_has = self._curl_pool.has_available()
        httpx_has = self._httpx_pool.has_available()

        if stealth_mode and not curl_has and not httpx_has:
            return "nodriver"
        if curl_has:
            return "curl"
        if httpx_has:
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
                "banned": getattr(self._httpx_pool, "banned_count", lambda: 0)(),
                "sessions": [s.to_dict() for s in self._httpx_pool.sessions],
            },
            "playwright": {
                "total": self._playwright_pool.size,
                "available": self._playwright_pool.available_count(),
                "sessions": [s.to_dict() for s in self._playwright_pool.sessions],
            },
            "nodriver": {
                "total": self._nodriver_pool.size,
                "available": self._nodriver_pool.available_count(),
                "sessions": [s.to_dict() for s in self._nodriver_pool.sessions],
            },
        }
