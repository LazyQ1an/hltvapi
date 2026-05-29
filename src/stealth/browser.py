"""Deep Nodriver browser management for single-IP Cloudflare bypass. v6.1

Enhanced with:
- CDP_FULL_ARMOR: comprehensive CDP domain blocking (Runtime, Page, Network,
  Browser, Target, Debugger, Input)
- Fingerprint fixation: same profile = same fingerprint forever
- Natural noise injection: Canvas/WebGL/Audio noise tuned to real hardware
- Profile-locked identity: all fingerprint values derived from profile seed

Usage:
    async with BrowserManager(settings, profile) as browser:
        html, status = await browser.fetch("https://www.hltv.org/matches")
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import time as tmod
from pathlib import Path
from typing import Any

from src.profiles.manager import Profile
from src.settings import StealthSettings

logger = logging.getLogger("hltv.stealth.browser")


class BrowserManager:
    """Deep Nodriver customization for Cloudflare bypass."""

    def __init__(
        self,
        settings: StealthSettings | None = None,
        profile: Profile | None = None,
    ) -> None:
        self._settings = settings or StealthSettings()
        self._profile = profile
        self._browser: Any = None
        self._page_count: int = 0
        self._last_activity: float = tmod.time()
        self._started: bool = False

        # Cached fingerprint script (computed once per profile if fixation enabled)
        self._cached_stealth_script: str | None = None

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    # ── Lifecycle ───────────────────────────────

    async def start(self) -> None:
        """Start the Nodriver browser with full stealth configuration."""
        if self._started:
            return

        try:
            import nodriver as uc
        except ImportError:
            raise RuntimeError(
                "nodriver not installed. Run: pip install nodriver"
            ) from None

        browser_args = self._build_chrome_args()
        chrome_path = self._resolve_chrome_path()

        logger.info(
            "Starting Nodriver v6.1 (headless=%s, profile=%s, deep_armor=%s, fingerprint_fix=%s)",
            self._settings.headless,
            self._profile.name if self._profile else "default",
            self._settings.cdp_deep_armor,
            self._settings.fingerprint_fixation,
        )

        try:
            self._browser = await uc.start(
                headless=self._settings.headless,
                browser_args=browser_args,
                browser_executable_path=chrome_path,
            )
            self._started = True

            # Pre-build the stealth script if fingerprint fixation is on
            if self._settings.fingerprint_fixation and self._profile:
                self._cached_stealth_script = self._build_profile_script()

            logger.info("Nodriver started successfully")
        except Exception as e:
            logger.error("Failed to start Nodriver: %s", e)
            raise

    async def stop(self) -> None:
        """Gracefully stop the browser."""
        if self._browser and self._started:
            try:
                self._browser.stop()
            except Exception as e:
                logger.debug("Nodriver stop: %s", e)
            self._started = False
            self._browser = None
            logger.info("Nodriver browser stopped")

    # ── Core fetch ──────────────────────────────

    async def fetch(
        self,
        url: str,
        *,
        warmup: bool = True,
        behavior: Any = None,
    ) -> tuple[str, int]:
        """Fetch a URL with full stealth + behavior simulation."""
        if not self._started:
            await self.start()

        if self._should_recycle():
            logger.debug("Recycling browser")
            await self.stop()
            await self.start()

        page = None
        try:
            if warmup:
                await self._warmup_homepage()

            page = await self._browser.get(url)
            self._page_count += 1
            self._last_activity = tmod.time()

            # Inject CDP deep armor
            if self._settings.cdp_deep_armor:
                try:
                    from src.stealth.cdp_patches import CDP_FULL_ARMOR
                    await page.evaluate(CDP_FULL_ARMOR)
                except ImportError:
                    await page.evaluate(CDP_CLEANUP_SCRIPT)
            elif self._settings.cdp_minimization:
                await page.evaluate(CDP_CLEANUP_SCRIPT)

            # Inject fingerprint spoofing (cached per profile)
            if self._cached_stealth_script:
                await page.evaluate(self._cached_stealth_script)
            else:
                try:
                    from src.antibot.fingerprint_spoofer import build_full_stealth_script
                    await page.evaluate(build_full_stealth_script())
                except ImportError:
                    pass

            # Behavior simulation
            if behavior:
                page_type = behavior.classify_url(url)
                await behavior.simulate_visit(page, page_type)

            # Wait for CF challenge resolution
            await self._wait_for_page(url, page)

            content = await page.get_content()
            await self._harvest_cookies(page, url)

            return content, 200

        except Exception as e:
            logger.error("Nodriver fetch failed for %s: %s", url, e)
            return "", 0
        finally:
            if page:
                try:
                    page.stop()
                except Exception:
                    pass

    # ── Internal helpers ────────────────────────

    async def _warmup_homepage(self) -> None:
        """Visit hltv.org homepage to obtain cf_clearance."""
        try:
            warm_page = await self._browser.get("https://www.hltv.org/")
            await asyncio.sleep(random.uniform(2.0, 5.0))

            if self._settings.cdp_deep_armor:
                try:
                    from src.stealth.cdp_patches import CDP_FULL_ARMOR
                    await warm_page.evaluate(CDP_FULL_ARMOR)
                except ImportError:
                    await warm_page.evaluate(CDP_CLEANUP_SCRIPT)
            else:
                await warm_page.evaluate(CDP_CLEANUP_SCRIPT)

            for _ in range(self._settings.cf_wait_timeout):
                content = await warm_page.get_content()
                if _has_hltv_markers(content):
                    break
                await asyncio.sleep(1.0)

            await self._harvest_cookies(warm_page, "https://www.hltv.org/")
            warm_page.stop()
            logger.debug("Homepage warmup complete")
        except Exception as e:
            logger.debug("Homepage warmup: %s", e)

    async def _wait_for_page(self, url: str, page: Any) -> None:
        """Poll until CF challenge resolves."""
        for _ in range(self._settings.cf_wait_timeout):
            try:
                content = await page.get_content()
            except Exception:
                await asyncio.sleep(0.5)
                continue

            if _has_hltv_markers(content):
                return

            lower = content.lower()
            is_cf = any(
                m in lower for m in (
                    "just a moment", "checking your browser",
                    "cf-browser-verification", "cf_challenge",
                    "__cf_chl_f_tk", "challenge-platform",
                    "cf-challenge", "turnstile",
                )
            )
            if not is_cf:
                return

            await asyncio.sleep(1.0)

    async def _harvest_cookies(self, page: Any, url: str) -> None:
        """Extract cookies from the page."""
        try:
            import nodriver as uc
            cookies = await page.send(uc.cdp.network.get_cookies(urls=[url]))
            cookie_dict = {}
            for c in (cookies or []):
                cookie_dict[c.name] = c.value

            if cookie_dict and self._profile:
                self._profile.save_cookies(cookie_dict)
                logger.debug(
                    "Harvested %d cookies (cf_clearance=%s)",
                    len(cookie_dict),
                    "cf_clearance" in cookie_dict,
                )
        except Exception as e:
            logger.debug("Cookie harvest: %s", e)

    def get_cookies(self) -> dict[str, str]:
        """Return profile cookies."""
        if self._profile:
            return self._profile._cookies
        return {}

    # ── Fingerprint fixation ────────────────────

    def _build_profile_script(self) -> str:
        """Build a deterministic stealth script from profile identity.

        The profile name is hashed to produce a stable seed. All fingerprint
        values (Canvas noise, WebGL GPU, Audio params, navigator properties)
        derive from this seed. Same profile = same fingerprint forever.
        """
        if self._profile is None:
            return ""

        seed = int(hashlib.sha256(self._profile.name.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        # Deterministic GPU selection
        gpu_profiles = [
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0)"),
            ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0)"),
            ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)"),
            ("Apple Inc.", "Apple M1"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0)"),
        ]
        gpu_vendor, gpu_renderer = rng.choice(gpu_profiles)

        hw = rng.choice([4, 8, 12, 16])
        dm = rng.choice([4, 8, 16])
        plat = rng.choice(["Win32", "MacIntel", "Linux x86_64"])
        canvas_noise = round(rng.uniform(0.0005, 0.003), 6)
        canvas_seed = rng.randint(1, 2**31 - 1)
        audio_sr = rng.choice([44100, 48000])

        script = f"""
(function() {{
    'use strict';

    // Navigator properties (deterministic per profile)
    Object.defineProperties(navigator, {{
        webdriver: {{ get: () => undefined }},
        hardwareConcurrency: {{ get: () => {hw} }},
        deviceMemory: {{ get: () => {dm} }},
        platform: {{ get: () => '{plat}' }},
        vendor: {{ get: () => 'Google Inc.' }},
        plugins: {{ get: () => [1, 2, 3, 4, 5] }},
        languages: {{ get: () => ['en-US', 'en'] }},
    }});

    // WebGL spoof (deterministic GPU)
    const origGetParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(p) {{
        if (p === 37445) return '{gpu_vendor}';
        if (p === 37446) return '{gpu_renderer}';
        return origGetParam.call(this, p);
    }};

    // Canvas noise (deterministic seed)
    let _rn = {canvas_seed};
    HTMLCanvasElement.prototype.toDataURL = function(...args) {{
        const ctx = this.getContext('2d');
        if (ctx && this.width > 0 && this.height > 0) {{
            const img = ctx.getImageData(0, 0, this.width, this.height);
            for (let i = 0; i < img.data.length; i += 4) {{
                _rn = (_rn * 16807) % 2147483647;
                const noise = (_rn / 2147483647) * 2 - 1;
                img.data[i] = Math.min(255, Math.max(0, img.data[i] + Math.round(noise * {canvas_noise} * 255)));
            }}
            ctx.putImageData(img, 0, 0);
        }}
        return origTDURL.call(this, ...args);
    }};
    const origTDURL = HTMLCanvasElement.prototype.toDataURL;

    // AudioContext spoof (deterministic)
    if (window.AudioContext || window.webkitAudioContext) {{
        const AC = window.AudioContext || window.webkitAudioContext;
        const origCreate = AC.prototype.createOscillator;
        AC.prototype.createOscillator = function() {{
            const osc = origCreate.call(this);
            osc.frequency.value = {audio_sr} + (Math.random() - 0.5) * 2;
            return osc;
        }};
    }}

    window.chrome = {{ runtime: {{}}, loadTimes: () => ({{}}), csi: () => ({{}}) }};
}})();
"""
        return script

    # ── Chrome args ─────────────────────────────

    def _build_chrome_args(self) -> list[str]:
        """Build Chrome CLI arguments for stealth + server optimization."""
        args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-automation",
            "--disable-features=TranslateUI,AudioServiceOutOfProcess,CalculateNativeWinOcclusion",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-infobars",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-component-update",
            "--disable-default-apps",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-extensions",
            "--disable-breakpad",
            "--disable-crash-reporter",
            "--disable-hang-monitor",
            "--disable-prompt-on-repost",
            "--disable-client-side-phishing-detection",
            "--disable-popup-blocking",
            "--password-store=basic",
            "--use-mock-keychain",
            f"--window-size={self._settings.window_width},{self._settings.window_height}",
        ]

        if self._profile:
            args.append(f"--user-data-dir={self._profile.user_data_dir}")

        # Extra user-provided args
        args.extend(self._settings.extra_chrome_args)

        return args

    def _resolve_chrome_path(self) -> str | None:
        """Auto-detect system Chrome path."""
        if self._settings.chrome_path:
            return self._settings.chrome_path

        candidates = [
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ]
        for path in candidates:
            if Path(path).exists():
                return path

        if os.name == "nt":
            for path in [
                "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            ]:
                if Path(path).exists():
                    return path

        mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if Path(mac).exists():
            return mac

        return None

    def _should_recycle(self) -> bool:
        """Check if the browser should be recycled."""
        if self._page_count >= self._settings.max_pages:
            return True
        idle = tmod.time() - self._last_activity
        if idle > self._settings.idle_timeout and self._page_count > 0:
            return True
        return False


# ── CDP cleanup (basic fallback) ────────────────

CDP_CLEANUP_SCRIPT = """
(function() {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true });
    delete Object.getPrototypeOf(navigator).webdriver;
    Object.keys(window).forEach(function(k) { if (k.startsWith('cdc_') || k.startsWith('_cdc_')) delete window[k]; });
    document.documentElement.removeAttribute('webdriver');
    window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
    var oq = window.navigator.permissions.query;
    window.navigator.permissions.query = function(p) { return p.name === 'notifications' ? Promise.resolve({ state: Notification.permission }) : oq(p); };
    Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
})();
"""


def _has_hltv_markers(html: str) -> bool:
    """Check if HTML contains HLTV markers."""
    lower = html.lower()
    return any(
        m.lower() in lower
        for m in (
            "hltv", "nav-bar", "standard-box", "match-wrapper",
            "teamsBox", "topnav", "sidebar", "footer-navigation",
        )
    )


__all__ = ["BrowserManager", "CDP_CLEANUP_SCRIPT"]
