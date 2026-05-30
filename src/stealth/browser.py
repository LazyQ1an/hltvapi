"""
Deep Nodriver browser management for single-IP Cloudflare bypass. NG1.0

NG1.0: Worker injection + micro-physics behavior + event chain completeness.
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
    """Deep Nodriver customization for Cloudflare bypass NG1.0."""

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
        self._cached_stealth_script: str | None = None
        self._worker_injector: Any = None

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    async def start(self) -> None:
        if self._started:
            return
        try:
            import nodriver as uc
        except ImportError:
            raise RuntimeError("nodriver not installed. Run: pip install nodriver") from None

        browser_args = self._build_chrome_args()
        chrome_path = self._resolve_chrome_path()

        logger.info("Starting Nodriver NG1.0 (headless=%s, profile=%s)", self._settings.headless, self._profile.name if self._profile else "default")

        try:
            self._browser = await uc.start(headless=self._settings.headless, browser_args=browser_args, browser_executable_path=chrome_path)
            self._started = True

            if self._settings.fingerprint_fixation and self._profile:
                self._cached_stealth_script = self._build_profile_script()

            # Initialize worker injector
            from src.stealth.worker_injector import WorkerInjector
            self._worker_injector = WorkerInjector(self._browser)

            logger.info("Nodriver NG1.0 started")
        except Exception as e:
            logger.error("Failed to start Nodriver: %s", e)
            raise

    async def stop(self) -> None:
        if self._browser and self._started:
            try:
                self._browser.stop()
            except Exception as e:
                logger.debug("Nodriver stop: %s", e)
            self._started = False
            self._browser = None

    async def fetch(self, url: str, *, warmup: bool = True, behavior: Any = None) -> tuple[str, int]:
        if not self._started:
            await self.start()
        if self._should_recycle():
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

            # Inject fingerprint
            if self._cached_stealth_script:
                await page.evaluate(self._cached_stealth_script)

            # Inject into ALL worker contexts (NG1.0)
            if self._worker_injector:
                await self._worker_injector.inject_all(self._cached_stealth_script or "")

            # Behavior simulation
            if behavior:
                page_type = behavior.classify_url(url)
                await behavior.simulate_visit(page, page_type)

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

    async def _warmup_homepage(self) -> None:
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
        except Exception as e:
            logger.debug("Homepage warmup: %s", e)

    async def _wait_for_page(self, url: str, page: Any) -> None:
        for _ in range(self._settings.cf_wait_timeout):
            try:
                content = await page.get_content()
            except Exception:
                await asyncio.sleep(0.5)
                continue
            if _has_hltv_markers(content):
                return
            lower = content.lower()
            is_cf = any(m in lower for m in ("just a moment", "checking your browser", "cf-browser-verification", "cf_challenge", "__cf_chl_f_tk", "challenge-platform", "cf-challenge", "turnstile"))
            if not is_cf:
                return
            await asyncio.sleep(1.0)

    async def _harvest_cookies(self, page: Any, url: str) -> None:
        try:
            import nodriver as uc
            cookies = await page.send(uc.cdp.network.get_cookies(urls=[url]))
            cookie_dict = {}
            for c in (cookies or []):
                cookie_dict[c.name] = c.value
            if cookie_dict and self._profile:
                self._profile.save_cookies(cookie_dict)
        except Exception as e:
            logger.debug("Cookie harvest: %s", e)

    def get_cookies(self) -> dict[str, str]:
        if self._profile:
            return self._profile._cookies
        return {}

    def _build_profile_script(self) -> str:
        if self._profile is None:
            return ""
        seed = int(hashlib.sha256(self._profile.name.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        gpu_profiles = [("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)"), ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0)"), ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)")]
        gpu_v, gpu_r = rng.choice(gpu_profiles)
        hw = rng.choice([4, 8, 12, 16])
        dm = rng.choice([4, 8, 16])
        plat = rng.choice(["Win32", "MacIntel", "Linux x86_64"])
        cs = rng.randint(1, 2**31 - 1)
        cn = round(rng.uniform(0.0005, 0.003), 6)
        return f"""(function(){{"use strict";Object.defineProperties(navigator,{{webdriver:{{get:()=>undefined}},hardwareConcurrency:{{get:()=>{hw}}},deviceMemory:{{get:()=>{dm}}},platform:{{get:()=>'{plat}'}},vendor:{{get:()=>'Google Inc.'}},plugins:{{get:()=>[1,2,3,4,5]}},languages:{{get:()=>['en-US','en']}}}});const og=WebGLRenderingContext.prototype.getParameter;WebGLRenderingContext.prototype.getParameter=function(p){{if(p===37445)return'{gpu_v}';if(p===37446)return'{gpu_r}';return og.call(this,p)}};let rn={cs};HTMLCanvasElement.prototype.toDataURL=function(...a){{const c=this.getContext('2d');if(c&&this.width>0){{const im=c.getImageData(0,0,this.width,this.height);for(let i=0;i<im.data.length;i+=4){{rn=(rn*16807)%2147483647;const n=(rn/2147483647)*2-1;im.data[i]=Math.min(255,Math.max(0,im.data[i]+Math.round(n*{cn}*255)))}}c.putImageData(im,0,0)}}return _origTDURL.apply(this,a)}};const _origTDURL=HTMLCanvasElement.prototype.toDataURL;window.chrome={{runtime:{{}},loadTimes:()=>({{}}),csi:()=>({{}})}};}})();"""

    def _build_chrome_args(self) -> list[str]:
        args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled", "--disable-automation", "--disable-features=TranslateUI,AudioServiceOutOfProcess,CalculateNativeWinOcclusion", "--use-gl=angle", "--use-angle=swiftshader", "--enable-webgl", "--disable-infobars", "--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding", "--disable-component-update", "--disable-default-apps", "--no-first-run", "--no-default-browser-check", "--disable-sync", "--disable-extensions", "--disable-breakpad", "--disable-crash-reporter", "--disable-hang-monitor", "--disable-prompt-on-repost", "--disable-client-side-phishing-detection", "--disable-popup-blocking", "--password-store=basic", "--use-mock-keychain", f"--window-size={self._settings.window_width},{self._settings.window_height}"]
        if self._profile:
            args.append(f"--user-data-dir={self._profile.user_data_dir}")
        args.extend(self._settings.extra_chrome_args)
        return args

    def _resolve_chrome_path(self) -> str | None:
        if self._settings.chrome_path:
            return self._settings.chrome_path
        for p in ["/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium", "/snap/bin/chromium"]:
            if Path(p).exists():
                return p
        if os.name == "nt":
            for p in ["C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"]:
                if Path(p).exists():
                    return p
        mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        return mac if Path(mac).exists() else None

    def _should_recycle(self) -> bool:
        if self._page_count >= self._settings.max_pages:
            return True
        return (tmod.time() - self._last_activity) > self._settings.idle_timeout and self._page_count > 0


CDP_CLEANUP_SCRIPT = """(function(){Object.defineProperty(navigator,'webdriver',{get:()=>undefined,configurable:true});delete Object.getPrototypeOf(navigator).webdriver;Object.keys(window).forEach(function(k){if(k.startsWith('cdc_')||k.startsWith('_cdc_'))delete window[k]});document.documentElement.removeAttribute('webdriver');window.chrome={runtime:{},loadTimes:function(){},csi:function(){},app:{}};var oq=window.navigator.permissions.query;window.navigator.permissions.query=function(p){return p.name==='notifications'?Promise.resolve({state:Notification.permission}):oq(p)};Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});})();"""


def _has_hltv_markers(html: str) -> bool:
    lower = html.lower()
    return any(m.lower() in lower for m in ("hltv", "nav-bar", "standard-box", "match-wrapper", "teamsBox", "topnav", "sidebar", "footer-navigation"))


__all__ = ["BrowserManager", "CDP_CLEANUP_SCRIPT"]
