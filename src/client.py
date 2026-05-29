"""
HLTV Client — clean async interface for single-IP scraping. v6.1

Two modes:
  "stealth"  (default) — Nodriver + CDP deep armor + fingerprint fixation
                          + ProfileManager smart selection + fatigue tracking
  "light"    — curl_cffi with TLS impersonation + real-time cookie sync + ETag

v6.1 enhancements:
  - FatigueTracker: IP-level metrics drive adaptive delay scaling
  - Hibernation: auto sleep 8-14h after daily quota or excessive blocks
  - ETag caching: If-None-Match / If-Modified-Since for light mode
  - Smart profile selection: health-weighted probabilistic choice
  - Real-time cookie sync on every request

Usage:
    async with HLTVClient(mode="stealth") as client:
        html = await client.get("https://www.hltv.org/matches")
"""

from __future__ import annotations

import asyncio
import logging
import random
import time as tmod
from typing import Any, Literal
from urllib.parse import urlparse

from src.settings import HLTVSettings, load_settings

logger = logging.getLogger("hltv.client")


class HLTVClient:
    """Main entry point for HLTV scraping.

    Public attributes (open interface):
        settings: HLTVSettings
        cookie_bridge: CookieBridge
        profiles: ProfileManager
        fatigue: FatigueTracker
    """

    def __init__(
        self,
        mode: Literal["stealth", "light"] | None = None,
        settings: HLTVSettings | None = None,
    ) -> None:
        self.settings = settings or load_settings(mode=mode)
        self.mode: str = self.settings.mode

        # Runtime state
        self._stealth_browser: Any = None
        self._behavior: Any = None
        self._light_session: Any = None
        self._profiles: Any = None
        self.cookie_bridge: Any = None
        self.fatigue: Any = None

        self._rate_state: dict[str, Any] = {
            "requests_this_hour": 0,
            "requests_today": 0,
            "hour_start": tmod.time(),
            "day_start": tmod.time(),
            "consecutive_blocks": 0,
            "cooldown_until": 0.0,
            "last_request": 0.0,
        }

        # ETag cache for light mode
        self._etag_cache: dict[str, str] = {}
        self._etag_last_modified: dict[str, str] = {}

        self._started = False

    @property
    def profiles(self) -> Any:
        return self._profiles

    # ── Lifecycle ───────────────────────────────

    async def __aenter__(self) -> "HLTVClient":
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def start(self) -> None:
        if self._started:
            return

        # Cookie bridge
        from src.sync.cookie_bridge import CookieBridge
        self.cookie_bridge = CookieBridge(self.settings.cache_dir)

        # Fatigue tracker
        from src.antibot.fatigue_tracker import FatigueTracker
        self.fatigue = FatigueTracker(self.settings)

        if self.mode == "stealth":
            await self._start_stealth()
        elif self.mode == "light":
            await self._start_light()
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

        self._started = True
        logger.info("HLTVClient v6.1 started (mode=%s)", self.mode)

    async def close(self) -> None:
        if self.mode == "stealth" and self._stealth_browser:
            try:
                await self._stealth_browser.stop()
            except Exception as e:
                logger.debug("Browser stop: %s", e)

        if self._light_session:
            try:
                await self._light_session.close()
            except Exception:
                pass

        self._started = False
        logger.info("HLTVClient closed")

    async def _start_stealth(self) -> None:
        from src.profiles.manager import ProfileManager
        from src.stealth.simulator import HumanBehaviorSimulator

        self._profiles = ProfileManager(self.settings.profile)
        await self._profiles.initialize()
        self._behavior = HumanBehaviorSimulator(self.settings.behavior)
        self._stealth_browser = None

    async def _start_light(self) -> None:
        try:
            from curl_cffi.requests import AsyncSession
        except ImportError:
            raise RuntimeError(
                "curl_cffi not installed. Run: pip install curl_cffi"
            ) from None

        self._light_session = AsyncSession(
            impersonate=self.settings.light.impersonate,  # type: ignore[arg-type]
            timeout=self.settings.light.timeout,
        )

        # Sync cookies from disk (if any)
        if self.cookie_bridge:
            self.cookie_bridge.inject_to_curl_session(self._light_session)

        logger.info(
            "Light mode ready (impersonate=%s, cookies=%d)",
            self.settings.light.impersonate,
            len(self.cookie_bridge._jar) if self.cookie_bridge else 0,
        )

    # ── Main API ─────────────────────────────────

    async def get(self, url: str) -> str:
        """Fetch an HLTV page with full anti-detection."""
        if not self._started:
            raise RuntimeError(
                "Client not started. Use 'async with HLTVClient()'."
            )

        # ── Hibernation check ──
        if self.settings.rate_limit.hibernation_enabled:
            if self.fatigue and self.fatigue.should_hibernate():
                remaining = self.fatigue.hibernation_remaining
                raise _HibernationError(
                    f"Hibernating for {remaining / 3600:.1f} more hours. "
                    f"Daily quota: {self.settings.rate_limit.requests_per_day}/day."
                )

        # ── Rate limit wait (with adaptive scaling) ──
        await self._rate_limit_wait(url)

        # ── Execute ──
        if self.mode == "stealth":
            return await self._get_stealth(url)
        else:
            return await self._get_light(url)

    async def get_json(self, url: str) -> dict[str, Any]:
        html = await self.get(url)
        import json
        return json.loads(html)

    async def get_bytes(self, url: str) -> bytes:
        if not self._started:
            raise RuntimeError("Client not started")
        if self.mode == "light":
            resp = await self._light_session.get(url)
            return resp.content
        else:
            html = await self._get_stealth(url)
            return html.encode("utf-8")

    # ── Backward-compatible helpers ────────────

    async def get_soup(
        self, url: str, *, parser: str = "html.parser", **kwargs: Any
    ) -> Any:
        html = await self.get(url)
        try:
            from src.parser import _HAS_SELECTOLAX
            if _HAS_SELECTOLAX:
                from selectolax.parser import HTMLParser
                return HTMLParser(html)
        except ImportError:
            pass
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, parser)

    async def _get_curl_session(self) -> Any | None:
        if self.mode == "light" and self._light_session:
            return self._light_session
        return None

    # ── Stealth implementation ──────────────────

    async def _get_stealth(self, url: str) -> str:
        max_retries = 3
        start_time = tmod.time()

        for attempt in range(max_retries):
            # Smart profile selection
            if self._profiles and self._profiles.should_rotate():
                await self._profiles.select()
                if self._stealth_browser:
                    await self._stealth_browser.stop()
                    self._stealth_browser = None

            # Lazy browser init
            if self._stealth_browser is None:
                from src.stealth.browser import BrowserManager
                profile = self._profiles.current if self._profiles else None
                self._stealth_browser = BrowserManager(
                    settings=self.settings.stealth,
                    profile=profile,
                )
                await self._stealth_browser.start()

            try:
                html, status = await self._stealth_browser.fetch(
                    url,
                    warmup=attempt == 0,
                    behavior=self._behavior,
                )

                rt = tmod.time() - start_time

                if not html or status == 0:
                    raise RuntimeError("Empty response")

                if status == 200 and len(html) > 5000 and not _looks_blocked(html):
                    self._rate_state["consecutive_blocks"] = 0
                    if self._profiles:
                        self._profiles.record_success(rt)
                    self.fatigue.record_request(response_time=rt, blocked=False)

                    # Harvest cookies
                    cookies = self._stealth_browser.get_cookies()
                    if cookies:
                        self.cookie_bridge.harvest_from_stealth(cookies)
                        self.fatigue.record_cookie("cf_clearance")

                    self._rate_state["last_request"] = tmod.time()
                    return html

                # Blocked
                self._rate_state["consecutive_blocks"] += 1
                if self._profiles:
                    self._profiles.record_block()
                self.fatigue.record_request(response_time=rt, blocked=True)

                logger.warning(
                    "Block on %s (attempt %d/%d, fatigue=%.2f)",
                    url, attempt + 1, max_retries, self.fatigue.score(),
                )

                if self._rate_state["consecutive_blocks"] >= self.settings.rate_limit.cooldown_after_blocks:
                    cooldown = self.settings.rate_limit.cooldown_minutes * 60
                    self._rate_state["cooldown_until"] = tmod.time() + cooldown
                    logger.warning("Forced cooldown for %.0f min", self.settings.rate_limit.cooldown_minutes)

                if self._profiles:
                    await self._profiles.select()
                continue

            except Exception as e:
                logger.warning("Stealth fetch error %s (attempt %d): %s", url, attempt + 1, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    from src.exceptions import HTTPError
                    raise HTTPError(
                        message=f"Stealth fetch failed after {max_retries} attempts: {e}",
                        url=url,
                    ) from e

        from src.exceptions import BlockedError
        raise BlockedError(
            message=f"All {max_retries} stealth attempts blocked: {url}",
            url=url,
        )

    # ── Light implementation ────────────────────

    async def _get_light(self, url: str) -> str:
        if self._light_session is None:
            raise RuntimeError("Light session not initialized")

        max_retries = self.settings.light.max_retries
        retry_delay = self.settings.light.retry_delay
        start_time = tmod.time()

        for attempt in range(max_retries):
            # Build headers
            headers = _build_light_headers(url)

            # Align with profile if enabled
            if self.settings.light.align_with_profile:
                headers = self._align_headers(headers)

            # Inject cookies from bridge
            if self.cookie_bridge:
                headers = self.cookie_bridge.inject_to_light_headers(headers)

            # ETag / If-Modified-Since
            if self.settings.light.etag_cache and url in self._etag_cache:
                headers["If-None-Match"] = self._etag_cache[url]
            if url in self._etag_last_modified:
                headers["If-Modified-Since"] = self._etag_last_modified[url]

            try:
                resp = await self._light_session.get(url, headers=headers)
                rt = tmod.time() - start_time

                # 304 Not Modified — use cached
                if resp.status_code == 304:
                    self._rate_state["last_request"] = tmod.time()
                    return ""  # Caller should handle

                if resp.status_code == 200:
                    html = resp.text

                    # Update ETag
                    if "ETag" in resp.headers:
                        self._etag_cache[url] = resp.headers["ETag"]
                    if "Last-Modified" in resp.headers:
                        self._etag_last_modified[url] = resp.headers["Last-Modified"]

                    # Trim ETag cache
                    if len(self._etag_cache) > self.settings.light.etag_cache_size:
                        oldest = sorted(self._etag_cache.keys())[:100]
                        for k in oldest:
                            self._etag_cache.pop(k, None)

                    if not _looks_blocked(html) and len(html) > 5000:
                        self._rate_state["consecutive_blocks"] = 0
                        self.fatigue.record_request(response_time=rt, blocked=False)
                        self._rate_state["last_request"] = tmod.time()
                        return html

                # Block or error
                logger.warning(
                    "Light: status=%d len=%d url=%s (attempt %d)",
                    resp.status_code, len(resp.text), url, attempt + 1,
                )

                self._rate_state["consecutive_blocks"] += 1
                self.fatigue.record_request(response_time=rt, blocked=True)

                if resp.status_code in (403, 429, 503) or _looks_blocked(resp.text):
                    if self._rate_state["consecutive_blocks"] >= self.settings.rate_limit.cooldown_after_blocks:
                        cooldown = self.settings.rate_limit.cooldown_minutes * 60
                        self._rate_state["cooldown_until"] = tmod.time() + cooldown

                    await asyncio.sleep(retry_delay * (2 ** attempt))
                    continue

                return resp.text

            except Exception as e:
                logger.warning("Light fetch error %s: %s", url, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2 ** attempt))

        from src.exceptions import BlockedError
        raise BlockedError(
            message=f"Light: all {max_retries} attempts failed: {url}",
            url=url,
        )

    # ── Adaptive rate limiting ──────────────────

    async def _rate_limit_wait(self, url: str) -> None:
        rl = self.settings.rate_limit
        now = tmod.time()

        # Reset counters
        if now - self._rate_state["hour_start"] > 3600:
            self._rate_state["requests_this_hour"] = 0
            self._rate_state["hour_start"] = now
        if now - self._rate_state["day_start"] > 86400:
            self._rate_state["requests_today"] = 0
            self._rate_state["day_start"] = now

        # Hard caps
        if self._rate_state["requests_this_hour"] >= rl.requests_per_hour:
            wait = 3600 - (now - self._rate_state["hour_start"])
            logger.warning("Hourly cap reached, waiting %.0fs", wait)
            await asyncio.sleep(min(wait, 3600))

        if self._rate_state["requests_today"] >= rl.requests_per_day:
            wait = 86400 - (now - self._rate_state["day_start"])
            logger.warning("Daily cap reached, waiting %.0fs", wait)
            await asyncio.sleep(min(wait, 86400))

        # Cooldown
        if now < self._rate_state["cooldown_until"]:
            wait = self._rate_state["cooldown_until"] - now
            logger.warning("Cooldown active, waiting %.0fs", wait)
            await asyncio.sleep(wait)

        # Base delay
        base_delay = random.uniform(rl.min_delay, rl.max_delay)
        if rl.jitter:
            base_delay += random.gauss(0, base_delay * 0.2)
        base_delay = max(0.5, base_delay)

        # Adaptive scaling from fatigue
        if rl.adaptive_enabled and self.fatigue:
            multiplier = self.fatigue.delay_multiplier()
            base_delay *= multiplier
            if multiplier > 2.0:
                logger.debug(
                    "Adaptive delay: %.1fs (fatigue=%.2f, x%.1f)",
                    base_delay, self.fatigue.score(), multiplier,
                )

        # Endpoint awareness
        if _is_detail_page(url):
            base_delay *= 2.0

        # Wait
        since_last = now - self._rate_state["last_request"]
        if since_last < base_delay:
            await asyncio.sleep(base_delay - since_last)

        self._rate_state["requests_this_hour"] += 1
        self._rate_state["requests_today"] += 1

    # ── Header alignment ────────────────────────

    def _align_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Align light mode headers with active stealth profile for consistency."""
        if not self._profiles or not self._profiles.current:
            return headers

        profile = self._profiles.current
        # Use a deterministic UA derived from profile seed
        chrome_versions = [
            "131.0.0.0", "133.0.0.0", "136.0.0.0",
        ]
        ver = chrome_versions[profile.fingerprint_seed % len(chrome_versions)]
        ua = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{ver} Safari/537.36"
        )
        headers["User-Agent"] = ua
        return headers

    # ── Stats ───────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        now = tmod.time()
        stats: dict[str, Any] = {
            "mode": self.mode,
            "started": self._started,
            "requests_this_hour": self._rate_state["requests_this_hour"],
            "requests_today": self._rate_state["requests_today"],
            "consecutive_blocks": self._rate_state["consecutive_blocks"],
            "cooldown_active": now < self._rate_state["cooldown_until"],
            "cookie_bridge": {
                "has_cf_clearance": bool(
                    self.cookie_bridge and self.cookie_bridge.get_cf_clearance()
                ),
                "clearance_valid": bool(
                    self.cookie_bridge and self.cookie_bridge.has_valid_clearance
                ),
            } if self.cookie_bridge else {},
            "profiles": (
                self._profiles.get_health_report()
                if self._profiles else {}
            ),
        }

        if self.fatigue:
            stats["fatigue"] = self.fatigue.get_stats()

        return stats


# ── Helpers ────────────────────────────────────

class _HibernationError(Exception):
    """Raised when the client is hibernating."""
    pass


def _looks_blocked(html: str) -> bool:
    if not html or len(html) < 300:
        return True
    lower = html.lower()
    block_markers = [
        "just a moment", "checking your browser",
        "cf-browser-verification", "cf_challenge",
        "__cf_chl_f_tk", "challenge-platform",
        "turnstile", "captcha", "blocked",
    ]
    hltv_markers = [
        "hltv", "nav-bar", "standard-box",
        "match-wrapper", "topnav", "sidebar",
    ]
    has_block = any(m in lower for m in block_markers)
    has_hltv = any(m in lower for m in hltv_markers)
    return has_block and not has_hltv


def _is_detail_page(url: str) -> bool:
    path = urlparse(url).path.lower()
    return (
        ("/matches/" in path and path.count("/") > 3)
        or ("/team/" in path)
        or ("/player/" in path)
        or ("/news/" in path and path.count("/") > 3)
        or ("/results/" in path and path.count("/") > 3)
    )


def _build_light_headers(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": f"{parsed.scheme}://{parsed.netloc}/",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


__all__ = ["HLTVClient", "_HibernationError"]
