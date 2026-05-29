"""
Nodriver (undetected-chromedriver successor) transport pool.

Nodriver drives the system Chrome directly via CDP with minimal
automation fingerprints. In 2026 testing, it achieves significantly
higher Cloudflare pass rates than patched Playwright, especially
in single-IP / no-proxy scenarios.

Key advantages over Playwright:
- Real browser binary (system Chrome), not bundled Chromium
- Minimized CDP calls reduce detectable automation patterns
- Native async throughout
- Built-in stealth (webdriver removal, permissions handling)
- Lighter resource footprint

Integration with fingerprint_spoofer:
- Canvas/WebGL/Audio spoofing injected via page.evaluate()
- Navigator properties matched to SessionIdentity
- Mouse movement, scroll, hover simulation for realism
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from ..base import TransportSession
from ..identity import SessionIdentity

logger = logging.getLogger("hltv.transport.nodriver_pool")


class NodriverContextPool:
    """Nodriver browser pool -- drives system Chrome with stealth.

    Each session wraps a nodriver Browser instance with per-context
    fingerprint spoofing and realistic behavior simulation.
    """

    def __init__(
        self,
        size: int = 1,
        config: Any = None,
    ) -> None:
        self.size = size
        self._config = config
        self.sessions: list[TransportSession] = []
        self._initialized = False

    async def _ensure_init(self) -> None:
        if self._initialized:
            return
        import importlib.util
        if importlib.util.find_spec("nodriver") is None:
            logger.warning("nodriver not available -- install with: pip install nodriver")
            return

        try:
            for _ in range(self.size):
                session = await self._create_session()
                self.sessions.append(session)

            self._initialized = True
            logger.info("Nodriver pool initialized (%d sessions)", self.size)
        except Exception as e:
            logger.error("Nodriver init failed: %s", e)

    async def _create_session(self) -> TransportSession:
        import nodriver as uc

        identity = SessionIdentity.random(random.choice(["win32", "darwin"]))
        session = TransportSession(transport="nodriver", identity=identity)

        # Build Chrome args for stealth
        import os
        headless = os.environ.get("HLTV_NODRIVER_HEADLESS", "true").lower() not in ("false", "0", "no")

        browser_args = [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            f"--window-size={identity.viewport_width},{identity.viewport_height}",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-component-update",
            "--disable-default-apps",
            "--no-first-run",
            "--no-default-browser-check",
            "--password-store=basic",
            "--use-mock-keychain",
        ]

        # Proxy support
        proxy_url = self._resolve_proxy()
        if proxy_url:
            browser_args.append(f"--proxy-server={proxy_url}")

        try:
            browser = await uc.start(
                headless=headless,
                browser_args=browser_args,
            )
            session.client = browser

            # Build and cache the deep stealth script
            try:
                from src.antibot.fingerprint_spoofer import build_full_stealth_script
                session._stealth_script = build_full_stealth_script(identity)
            except ImportError:
                session._stealth_script = None

            # Store behavior simulation config
            session._behavior = {
                "mouse_moves": random.randint(2, 6),
                "scroll_depth": random.randint(200, 800),
                "hover_count": random.randint(1, 3),
                "typing_delay_ms": random.randint(50, 200),
                "page_dwell_seconds": random.uniform(3.0, 12.0),
            }

        except Exception as e:
            logger.error("Failed to create nodriver session: %s", e)
            session.health_score = 0.0

        return session

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

        candidates = [s for s in self.sessions if not s.banned and s.client is not None]
        if not candidates:
            return None

        selected = candidates[0]
        self.sessions.remove(selected)
        self.sessions.append(selected)
        return selected

    def release(self, session_id: str, success: bool) -> None:
        for s in self.sessions:
            if s.id == session_id:
                if success:
                    s.record_success()
                else:
                    s.record_block()
                break

    def has_available(self) -> bool:
        if not self._initialized:
            return self.size > 0
        return any(s.client is not None and not s.banned for s in self.sessions)

    def available_count(self) -> int:
        if not self._initialized:
            return self.size
        return sum(1 for s in self.sessions if not s.banned and s.client is not None)

    async def close(self) -> None:
        for s in self.sessions:
            if s.client is not None:
                try:
                    await s.client.stop()
                except Exception:
                    pass
        logger.info("Nodriver pool closed")


async def nodriver_fetch(
    session: TransportSession,
    url: str,
    warmup_urls: list[str] | None = None,
) -> tuple[str, int]:
    """Execute a page fetch via Nodriver with full stealth + behavior simulation.

    Args:
        session: TransportSession with nodriver Browser as client.
        url: Target URL to fetch.
        warmup_urls: Optional list of URLs to visit before the target
                     (simulates natural browsing path).

    Returns:
        (html_content, status_code) tuple.
    """
    import nodriver as uc  # noqa: F811
    browser = session.client
    if browser is None:
        raise RuntimeError("Nodriver browser not initialized")

    behavior = getattr(session, "_behavior", {})
    stealth_script = getattr(session, "_stealth_script", None)
    page = None

    try:
        # --- Warmup: simulate natural browsing path ---
        if warmup_urls:
            for wurl in warmup_urls:
                try:
                    warm_page = await browser.get(wurl)
                    await asyncio.sleep(random.uniform(1.5, 4.0))
                    warm_page.stop()
                except Exception:
                    pass

        # --- Navigate to target ---
        page = await browser.get(url)

        # --- Inject stealth script ---
        if stealth_script:
            try:
                await page.evaluate(stealth_script)
            except Exception:
                pass

        # --- Simulate human behavior ---
        # Mouse movements
        mouse_moves = behavior.get("mouse_moves", 3)
        for _ in range(mouse_moves):
            try:
                x = random.randint(100, 1200)
                y = random.randint(100, 700)
                await page.evaluate(
                    f"document.elementFromPoint({x},{y})?.dispatchEvent(new MouseEvent('mousemove',{{clientX:{x},clientY:{y},bubbles:true}}))"
                )
                await asyncio.sleep(random.uniform(0.1, 0.4))
            except Exception:
                pass

        # Scroll
        scroll_depth = behavior.get("scroll_depth", 400)
        try:
            await page.evaluate(f"window.scrollTo({{top:{scroll_depth},behavior:'smooth'}})")
            await asyncio.sleep(random.uniform(0.3, 0.8))
            await page.evaluate(
                f"window.scrollTo({{top:{scroll_depth + random.randint(50,300)},behavior:'smooth'}})"
            )
        except Exception:
            pass

        # Hover over elements
        hover_count = behavior.get("hover_count", 1)
        for _ in range(hover_count):
            try:
                await page.evaluate(
                    "const links=document.querySelectorAll('a');"
                    "if(links.length){"
                    "const l=links[Math.floor(Math.random()*links.length)];"
                    "l.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));"
                    "}"
                )
                await asyncio.sleep(random.uniform(0.2, 0.5))
            except Exception:
                pass

        # --- Dwell time (simulate reading) ---
        dwell = behavior.get("page_dwell_seconds", 6.0)
        await asyncio.sleep(dwell)

        # --- Check for CF challenge ---
        content = await page.get_content()

        # Poll for CF challenge resolution (up to 25 seconds)
        for attempt in range(25):
            content_lower = content.lower()
            has_hltv = any(
                marker.lower() in content_lower
                for marker in ["hltv", "nav-bar", "standard-box", "match-wrapper",
                               "teamsBox", "topnav", "sidebar", "footer-navigation"]
            )
            if has_hltv:
                break

            is_cf = any(
                ind in content_lower
                for ind in ["just a moment", "checking your browser",
                            "cf-browser-verification", "cf_challenge",
                            "__cf_chl_f_tk", "challenge-platform",
                            "cf-challenge", "turnstile"]
            )
            if not is_cf:
                break

            await asyncio.sleep(1.0)
        else:
            await asyncio.sleep(3.0)

        content = await page.get_content()

        # --- Harvest cookies (cf_clearance, __cf_bm, etc.) ---
        try:
            cookies = await page.send(
                uc.cdp.network.get_cookies(urls=[url])
            )
            for c in cookies:
                session.cookie_jar[c.name] = c.value
        except Exception:
            pass

        return content, 200

    except Exception as e:
        logger.error("Nodriver fetch failed: %s", e)
        raise
    finally:
        if page:
            try:
                page.stop()
            except Exception:
                pass


async def nodriver_warmup_homepage(session: TransportSession) -> dict[str, Any]:
    """Warm up by visiting hltv.org homepage to obtain cf_clearance.

    Returns dict with cf_clearance status.
    """
    result: dict[str, Any] = {"cf_clearance": False, "cookies": 0}
    try:
        html, _ = await nodriver_fetch(
            session,
            "https://www.hltv.org/",
        )
        if session.cookie_jar:
            result["cookies"] = len(session.cookie_jar)
            if "cf_clearance" in session.cookie_jar:
                result["cf_clearance"] = True
    except Exception as e:
        result["error"] = str(e)
    return result


__all__ = [
    "NodriverContextPool",
    "nodriver_fetch",
    "nodriver_warmup_homepage",
]