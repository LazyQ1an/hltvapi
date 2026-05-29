"""
HLTV Client — v8.0 worker-aware, micro-physics survival.

v8.0 additions:
- HoneypotDetector: pre-parse scan before data extraction
- TLSSessionManager: TLS session persistence for light mode
- WorkerInjector: CDP-level injection into all targets
- Behavior v3: micro-physics mouse + complete pointer event chains
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
    """Main entry point for HLTV scraping v8.0.

    Public attributes: settings, cookie_bridge, profiles, fatigue, brain, honeypot, tls
    """

    def __init__(self, mode: Literal["stealth", "light"] | None = None, settings: HLTVSettings | None = None) -> None:
        self.settings = settings or load_settings(mode=mode)
        self.mode: str = self.settings.mode
        self._stealth_browser: Any = None
        self._behavior: Any = None
        self._light_session: Any = None
        self._profiles: Any = None
        self.cookie_bridge: Any = None
        self.fatigue: Any = None
        self.brain: Any = None
        self.honeypot: Any = None
        self.tls: Any = None
        self._rate_state: dict[str, Any] = {"requests_this_hour": 0, "requests_today": 0, "hour_start": tmod.time(), "day_start": tmod.time(), "consecutive_blocks": 0, "cooldown_until": 0.0, "last_request": 0.0}
        self._etag_cache: dict[str, str] = {}
        self._etag_last_modified: dict[str, str] = {}
        self._started = False

    @property
    def profiles(self) -> Any:
        return self._profiles

    async def __aenter__(self) -> "HLTVClient":
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def start(self) -> None:
        if self._started:
            return
        from src.sync.cookie_bridge import CookieBridge
        from src.antibot.fatigue_tracker import FatigueTracker
        from src.core.survival_brain import SurvivalBrain
        from src.antibot.honeypot_detector import HoneypotDetector
        from src.antibot.tls_session import TLSSessionManager

        self.cookie_bridge = CookieBridge(self.settings.cache_dir)
        self.fatigue = FatigueTracker(self.settings)
        self.brain = SurvivalBrain(self.settings)
        self.honeypot = HoneypotDetector()
        self.tls = TLSSessionManager(self.settings.cache_dir)

        if self.mode == "stealth":
            await self._start_stealth()
        elif self.mode == "light":
            await self._start_light()
        else:
            raise ValueError(f"Unknown mode: {self.mode}")
        self._started = True
        logger.info("HLTVClient v8.0 started (mode=%s)", self.mode)

    async def close(self) -> None:
        if self.mode == "stealth" and self._stealth_browser:
            try:
                await self._stealth_browser.stop()
            except Exception as e:
                logger.debug("Browser stop: %s", e)
        if self._light_session:
            if self.tls:
                self.tls.save_session(self._light_session)
            try:
                await self._light_session.close()
            except Exception:
                pass
        self._started = False

    async def _start_stealth(self) -> None:
        from src.profiles.manager import ProfileManager
        self._profiles = ProfileManager(self.settings.profile)
        await self._profiles.initialize()
        if self.settings.behavior.use_v2:
            try:
                from src.stealth.behavior_v3 import HumanBehaviorV3
                self._behavior = HumanBehaviorV3(self.settings.behavior)
            except ImportError:
                from src.stealth.behavior_v2 import HumanBehaviorV2, BehaviorProfile
                seed = self._profiles.current.fingerprint_seed if self._profiles.current else 42
                self._behavior = HumanBehaviorV2(self.settings.behavior, BehaviorProfile.from_seed(seed))
        else:
            from src.stealth.simulator import HumanBehaviorSimulator
            self._behavior = HumanBehaviorSimulator(self.settings.behavior)
        self._stealth_browser = None

    async def _start_light(self) -> None:
        try:
            from curl_cffi.requests import AsyncSession
        except ImportError:
            raise RuntimeError("curl_cffi not installed.") from None
        self._light_session = AsyncSession(impersonate=self.settings.light.impersonate, timeout=self.settings.light.timeout)  # type: ignore[arg-type]
        if self.tls:
            self.tls.restore_session(self._light_session)
        if self.cookie_bridge:
            self.cookie_bridge.inject_to_curl_session(self._light_session)
        logger.info("Light mode ready (impersonate=%s, tls=%s)", self.settings.light.impersonate, "restored" if self.tls and self.tls._tickets else "fresh")

    async def get(self, url: str) -> str:
        if not self._started:
            raise RuntimeError("Client not started.")
        if self.settings.rate_limit.hibernation_enabled and self.fatigue and self.fatigue.should_hibernate():
            raise _HibernationError(f"Hibernating {self.fatigue.hibernation_remaining/3600:.1f}h")

        request_type = _classify_request_type(url)
        profile_health = self._profiles.current.health_score if self._profiles and self._profiles.current else 1.0
        fatigue_score = self.fatigue.score() if self.fatigue else 0.0

        if self.settings.rate_limit.use_survival_brain and self.brain:
            can_proceed, delay = await self.brain.should_request(url, profile_id=self._profiles.current.name if self._profiles and self._profiles.current else "default", request_type=request_type, profile_health=profile_health, fatigue_score=fatigue_score)
            if not can_proceed:
                raise _RateLimitError(f"Rate limit: {url}")
            since_last = tmod.time() - self._rate_state["last_request"]
            if since_last < delay:
                await asyncio.sleep(delay - since_last)
        else:
            await self._rate_limit_wait(url)

        html = await (self._get_stealth(url) if self.mode == "stealth" else self._get_light(url))

        # Honeypot scan (v8.0)
        if self.honeypot and html:
            scan = await self.honeypot.scan(html)
            if scan["threat_level"] in ("high",):
                logger.warning("Honeypot alert for %s: %s", url, scan["details"])
                if scan["recommendation"] == "abort_and_sleep":
                    raise _BlockedError(f"Honeypot detected: {url}")

        return html

    async def get_json(self, url: str) -> dict[str, Any]:
        import json
        return json.loads(await self.get(url))

    async def get_bytes(self, url: str) -> bytes:
        if self.mode == "light":
            resp = await self._light_session.get(url)
            return resp.content
        html = await self._get_stealth(url)
        return html.encode("utf-8")

    async def get_soup(self, url: str, *, parser: str = "html.parser", **kwargs: Any) -> Any:
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
        return self._light_session if self.mode == "light" and self._light_session else None

    async def _get_stealth(self, url: str) -> str:
        max_retries = 3
        start_time = tmod.time()
        for attempt in range(max_retries):
            if self._profiles and self._profiles.should_rotate():
                await self._profiles.select()
                if self._stealth_browser:
                    await self._stealth_browser.stop()
                    self._stealth_browser = None
            if self._stealth_browser is None:
                from src.stealth.browser import BrowserManager
                profile = self._profiles.current if self._profiles else None
                self._stealth_browser = BrowserManager(settings=self.settings.stealth, profile=profile)
                await self._stealth_browser.start()
            try:
                html, status = await self._stealth_browser.fetch(url, warmup=attempt == 0, behavior=self._behavior)
                rt = tmod.time() - start_time
                if not html or status == 0:
                    raise RuntimeError("Empty response")
                if status == 200 and len(html) > 5000 and not _looks_blocked(html):
                    self._rate_state["consecutive_blocks"] = 0
                    if self._profiles:
                        self._profiles.record_success(rt)
                    self.fatigue.record_request(response_time=rt, blocked=False)
                    if self.brain:
                        self.brain.delay_calc.record_success()
                        self.brain.limiter.report_success(self._profiles.current.name if self._profiles and self._profiles.current else "default")
                    cookies = self._stealth_browser.get_cookies()
                    if cookies:
                        self.cookie_bridge.harvest_from_stealth(cookies)
                        self.fatigue.record_cookie("cf_clearance")
                    if self.settings.rate_limit.content_change_detection and self.brain:
                        self.brain.check_content_changed(url, html)
                    self._rate_state["last_request"] = tmod.time()
                    return html
                self._rate_state["consecutive_blocks"] += 1
                if self._profiles:
                    self._profiles.record_block()
                self.fatigue.record_request(response_time=rt, blocked=True)
                if self.brain:
                    self.brain.delay_calc.record_block()
                    self.brain.limiter.report_block(self._profiles.current.name if self._profiles and self._profiles.current else "default")
                if self._rate_state["consecutive_blocks"] >= self.settings.rate_limit.cooldown_after_blocks:
                    self._rate_state["cooldown_until"] = tmod.time() + self.settings.rate_limit.cooldown_minutes * 60
                if self._profiles:
                    await self._profiles.select()
                continue
            except Exception as e:
                logger.warning("Stealth error %s (attempt %d): %s", url, attempt + 1, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    from src.exceptions import HTTPError
                    raise HTTPError(message=f"Stealth failed after {max_retries}: {e}", url=url) from e
        from src.exceptions import BlockedError
        raise BlockedError(message=f"All {max_retries} attempts blocked: {url}", url=url)

    async def _get_light(self, url: str) -> str:
        if self._light_session is None:
            raise RuntimeError("Light session not initialized")
        max_retries = self.settings.light.max_retries
        retry_delay = self.settings.light.retry_delay
        start_time = tmod.time()
        for attempt in range(max_retries):
            headers = _build_light_headers(url)
            if self.settings.light.align_with_profile:
                headers = self._align_headers(headers)
            if self.cookie_bridge:
                headers = self.cookie_bridge.inject_to_light_headers(headers)
            if self.settings.light.etag_cache and url in self._etag_cache:
                headers["If-None-Match"] = self._etag_cache[url]
            if url in self._etag_last_modified:
                headers["If-Modified-Since"] = self._etag_last_modified[url]
            try:
                resp = await self._light_session.get(url, headers=headers)
                rt = tmod.time() - start_time
                # Save TLS state
                if self.tls:
                    self.tls.save_session(self._light_session)
                    if hasattr(resp, 'headers'):
                        self.tls.save_response_headers("hltv.org", dict(resp.headers))
                if resp.status_code == 304:
                    self._rate_state["last_request"] = tmod.time()
                    return ""
                if resp.status_code == 200:
                    html = resp.text
                    if "ETag" in resp.headers:
                        self._etag_cache[url] = resp.headers["ETag"]
                    if "Last-Modified" in resp.headers:
                        self._etag_last_modified[url] = resp.headers["Last-Modified"]
                    if not _looks_blocked(html) and len(html) > 5000:
                        self._rate_state["consecutive_blocks"] = 0
                        self.fatigue.record_request(response_time=rt, blocked=False)
                        if self.brain:
                            self.brain.delay_calc.record_success()
                        self._rate_state["last_request"] = tmod.time()
                        return html
                self._rate_state["consecutive_blocks"] += 1
                self.fatigue.record_request(response_time=rt, blocked=True)
                if self.brain:
                    self.brain.delay_calc.record_block()
                if resp.status_code in (403, 429, 503) or _looks_blocked(resp.text):
                    if self._rate_state["consecutive_blocks"] >= self.settings.rate_limit.cooldown_after_blocks:
                        self._rate_state["cooldown_until"] = tmod.time() + self.settings.rate_limit.cooldown_minutes * 60
                    await asyncio.sleep(retry_delay * (2 ** attempt))
                    continue
                return resp.text
            except Exception as e:
                logger.warning("Light error %s: %s", url, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2 ** attempt))
        from src.exceptions import BlockedError
        raise BlockedError(message=f"Light: all {max_retries} attempts failed: {url}", url=url)

    async def _rate_limit_wait(self, url: str) -> None:
        rl = self.settings.rate_limit
        now = tmod.time()
        if now - self._rate_state["hour_start"] > 3600:
            self._rate_state["requests_this_hour"] = 0
            self._rate_state["hour_start"] = now
        if now - self._rate_state["day_start"] > 86400:
            self._rate_state["requests_today"] = 0
            self._rate_state["day_start"] = now
        if self._rate_state["requests_this_hour"] >= rl.requests_per_hour:
            await asyncio.sleep(min(3600 - (now - self._rate_state["hour_start"]), 3600))
        if self._rate_state["requests_today"] >= rl.requests_per_day:
            await asyncio.sleep(min(86400 - (now - self._rate_state["day_start"]), 86400))
        if now < self._rate_state["cooldown_until"]:
            await asyncio.sleep(self._rate_state["cooldown_until"] - now)
        base_delay = random.uniform(rl.min_delay, rl.max_delay)
        if rl.jitter:
            base_delay += random.gauss(0, base_delay * 0.2)
        base_delay = max(0.5, base_delay)
        if rl.adaptive_enabled and self.fatigue:
            base_delay *= self.fatigue.delay_multiplier()
        if _is_detail_page(url):
            base_delay *= 2.0
        since_last = now - self._rate_state["last_request"]
        if since_last < base_delay:
            await asyncio.sleep(base_delay - since_last)
        self._rate_state["requests_this_hour"] += 1
        self._rate_state["requests_today"] += 1

    def _align_headers(self, headers: dict[str, str]) -> dict[str, str]:
        if not self._profiles or not self._profiles.current:
            return headers
        profile = self._profiles.current
        versions = ["131.0.0.0", "133.0.0.0", "136.0.0.0"]
        headers["User-Agent"] = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{versions[profile.fingerprint_seed % len(versions)]} Safari/537.36"
        return headers

    def get_stats(self) -> dict[str, Any]:
        now = tmod.time()
        stats: dict[str, Any] = {"mode": self.mode, "started": self._started, "requests_this_hour": self._rate_state["requests_this_hour"], "requests_today": self._rate_state["requests_today"], "consecutive_blocks": self._rate_state["consecutive_blocks"], "cooldown_active": now < self._rate_state["cooldown_until"]}
        if self.cookie_bridge:
            stats["cookie_bridge"] = {"has_cf_clearance": bool(self.cookie_bridge.get_cf_clearance()), "clearance_valid": self.cookie_bridge.has_valid_clearance}
        if self._profiles:
            stats["profiles"] = self._profiles.get_health_report()
        if self.fatigue:
            stats["fatigue"] = self.fatigue.get_stats()
        if self.brain:
            stats["brain"] = self.brain.get_stats()
        if self.honeypot:
            stats["honeypot"] = self.honeypot.get_stats()
        if self.tls:
            stats["tls"] = {"quic_domains": list(self.tls.quic_domains), "tickets": len(self.tls._tickets)}
        return stats


class _HibernationError(Exception):
    pass


class _RateLimitError(Exception):
    pass


class _BlockedError(Exception):
    pass


def _looks_blocked(html: str) -> bool:
    if not html or len(html) < 300:
        return True
    lower = html.lower()
    return any(m in lower for m in ("just a moment", "checking your browser", "cf-browser-verification", "cf_challenge", "__cf_chl_f_tk", "challenge-platform", "turnstile", "captcha", "blocked")) and not any(m in lower for m in ("hltv", "nav-bar", "standard-box", "match-wrapper", "topnav", "sidebar"))


def _is_detail_page(url: str) -> bool:
    path = urlparse(url).path.lower()
    return ("/matches/" in path and path.count("/") > 3) or "/team/" in path or "/player/" in path or ("/news/" in path and path.count("/") > 3) or ("/results/" in path and path.count("/") > 3)


def _classify_request_type(url: str) -> str:
    path = urlparse(url).path.lower()
    if "/search" in path:
        return "search"
    if any(p in path and path.count("/") > 3 for p in ("/matches/", "/results/", "/team/", "/player/", "/news/", "/events/")):
        return "detail"
    if any(p in path for p in ("/matches", "/results", "/ranking", "/events", "/stats")):
        return "listing"
    return "home" if path in ("/", "") else "other"


def _build_light_headers(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    return {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate, br", "Referer": f"{parsed.scheme}://{parsed.netloc}/", "DNT": "1", "Upgrade-Insecure-Requests": "1", "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin", "Sec-Fetch-User": "?1", "Cache-Control": "max-age=0"}


__all__ = ["HLTVClient"]
