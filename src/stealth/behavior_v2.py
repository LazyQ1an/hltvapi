"""
Human Behavior Engine v2 — per-profile behavior patterns. v7.0

Upgraded from v6.1 simulator with:
- Per-profile behavior profiles (derived from profile seed)
- Keyboard input simulation (typing speed, key intervals)
- Tab/window focus change events
- Scroll depth patterns (short vs deep scrollers)
- Mouse speed profiles (fast vs deliberate movers)
- Interaction frequency (active vs passive browsers)

Each profile gets a unique behavior "personality" that persists
across sessions, making multi-profile rotation more convincing.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("hltv.stealth.behavior_v2")


@dataclass
class BehaviorProfile:
    """A single behavior personality. Derived from profile seed."""

    # Mouse behavior
    mouse_speed: float = 1.0      # 0.5=slow, 1.0=normal, 2.0=fast
    mouse_curve_points: int = 5    # Bezier curve fidelity
    mouse_wiggle: bool = True      # Whether to add micro-wiggles

    # Scroll behavior
    scroll_depth: float = 0.5      # 0.1=shallow, 0.5=medium, 1.0=deep
    scroll_speed: float = 1.0      # 0.5=slow, 1.0=normal, 2.0=fast
    scroll_pauses: bool = True     # Whether to pause mid-scroll

    # Interaction frequency
    interaction_rate: float = 0.05 # 0.01=rare, 0.05=normal, 0.15=active
    hover_duration: float = 0.5    # How long to hover over elements

    # Keyboard
    typing_speed_wpm: int = 45     # Words per minute
    backspace_rate: float = 0.05   # How often to backspace

    # Dwell
    dwell_multiplier: float = 1.0  # 0.5=skimmer, 1.0=normal, 2.0=reader

    # Tab/window focus
    tab_switch_probability: float = 0.02  # Per-page chance of tab switch
    blur_duration: float = 5.0     # How long to stay "away"

    @classmethod
    def from_seed(cls, seed: int) -> "BehaviorProfile":
        rng = random.Random(seed)
        return cls(
            mouse_speed=round(rng.uniform(0.6, 1.8), 2),
            mouse_curve_points=rng.choice([3, 5, 7]),
            mouse_wiggle=rng.random() < 0.7,
            scroll_depth=round(rng.uniform(0.2, 0.9), 2),
            scroll_speed=round(rng.uniform(0.6, 1.5), 2),
            scroll_pauses=rng.random() < 0.6,
            interaction_rate=round(rng.uniform(0.02, 0.12), 3),
            hover_duration=round(rng.uniform(0.2, 1.2), 2),
            typing_speed_wpm=rng.randint(30, 70),
            backspace_rate=round(rng.uniform(0.02, 0.08), 3),
            dwell_multiplier=round(rng.uniform(0.6, 1.8), 2),
            tab_switch_probability=round(rng.uniform(0.0, 0.05), 3),
            blur_duration=round(rng.uniform(3.0, 15.0), 1),
        )


class HumanBehaviorV2:
    """Advanced human behavior simulation with per-profile personalities.

    Usage:
        behavior = HumanBehaviorV2(settings, behavior_profile)
        await behavior.simulate_visit(page, "match_detail")
    """

    def __init__(
        self,
        settings: Any = None,
        behavior_profile: BehaviorProfile | None = None,
    ) -> None:
        if settings is None:
            from src.settings import BehaviorSettings
            settings = BehaviorSettings()
        self._s = settings
        self._bp = behavior_profile or BehaviorProfile()

    def classify_url(self, url: str) -> str:
        path = url.lower()
        if "/search" in path:
            return "search"
        for p in ("/matches/", "/results/", "/team/", "/player/", "/news/", "/events/"):
            if p in path and path.count("/") > 3:
                return "detail"
        for p in ("/matches", "/results", "/ranking", "/events", "/stats"):
            if p in path:
                return "listing"
        if path in ("/", ""):
            return "home"
        return "other"

    async def simulate_visit(self, page: Any, page_type: str = "listing") -> None:
        """Full behavior simulation for a page visit."""
        try:
            # 1. Initial rendering pause
            await asyncio.sleep(random.uniform(0.3, 1.0))

            # 2. Tab focus simulation
            if random.random() < self._bp.tab_switch_probability:
                await self._simulate_tab_switch(page)

            # 3. Mouse movement
            for _ in range(self._s.mouse_move_count):
                await self._move_mouse_curve_v2(page)
                await asyncio.sleep(0.1 / self._bp.mouse_speed)

            # 4. Scroll
            if random.random() < self._s.scroll_probability:
                await self._scroll_v2(page, page_type)

            # 5. Light interaction
            if random.random() < self._bp.interaction_rate:
                await self._interact_v2(page, page_type)

            # 6. Keyboard (very rare, mostly for search)
            if page_type == "search" and random.random() < 0.3:
                await self._simulate_typing(page)

            # 7. Dwell
            await self._dwell_v2(page_type)

        except Exception as e:
            logger.debug("Behavior v2: %s", e)

    async def _move_mouse_curve_v2(self, page: Any) -> None:
        """Bezier mouse movement with per-profile speed."""
        try:
            n = self._bp.mouse_curve_points
            x0, y0 = random.randint(50, 300), random.randint(50, 300)
            x3, y3 = random.randint(400, 1500), random.randint(100, 700)
            x1 = x0 + random.randint(-200, 400)
            y1 = y0 + random.randint(-200, 200)
            x2 = x3 + random.randint(-400, 200)
            y2 = y3 + random.randint(-200, 200)

            for i in range(n + 1):
                t = i / n
                u = 1 - t
                x = int(u**3 * x0 + 3 * u**2 * t * x1 + 3 * u * t**2 * x2 + t**3 * x3)
                y = int(u**3 * y0 + 3 * u**2 * t * y1 + 3 * u * t**2 * y2 + t**3 * y3)

                # Wiggle
                if self._bp.mouse_wiggle:
                    x += random.randint(-2, 2)
                    y += random.randint(-2, 2)

                await page.evaluate(
                    f"(function(){{var e=document.elementFromPoint({x},{y});if(e)e.dispatchEvent(new MouseEvent('mousemove',{{clientX:{x},clientY:{y},bubbles:true}}));}})()"
                )
                await asyncio.sleep(random.uniform(0.003, 0.02) / self._bp.mouse_speed)
        except Exception:
            pass

    async def _scroll_v2(self, page: Any, page_type: str) -> None:
        """Scroll with per-profile depth and speed."""
        try:
            max_scroll = int(self._s.scroll_pixels_max * self._bp.scroll_depth)
            total = random.randint(self._s.scroll_pixels_min, max_scroll)
            steps = random.randint(3, 7)
            remaining = total

            for i in range(steps):
                progress = (i + 1) / steps
                if progress < 0.3:
                    factor = progress / 0.3
                elif progress > 0.7:
                    factor = (1.0 - progress) / 0.3
                else:
                    factor = 1.0

                step_px = int(remaining * factor * 0.4)
                step_px = max(10, min(step_px, remaining))
                remaining -= step_px

                await page.evaluate(
                    f"window.scrollBy({{top: {step_px}, left: 0, behavior: 'auto'}})"
                )
                interval = random.uniform(0.02, 0.10) / self._bp.scroll_speed

                if self._bp.scroll_pauses and i > 0 and random.random() < 0.3:
                    interval += random.uniform(0.2, 0.8)

                await asyncio.sleep(interval)
        except Exception:
            pass

    async def _interact_v2(self, page: Any, page_type: str) -> None:
        """Light interaction with per-profile style."""
        try:
            actions = [
                'var e=document.querySelector("[class*=search],[id*=search],input[type=text]");if(e)e.dispatchEvent(new MouseEvent("mouseover",{bubbles:true}));',
                'var l=document.querySelectorAll("a[href]");if(l.length>3)l[Math.floor(Math.random()*Math.min(l.length,10))].dispatchEvent(new MouseEvent("mouseover",{bubbles:true}));',
                'var r=document.querySelectorAll("tr,.result,.match,[class*=row]");if(r.length>1)r[Math.floor(Math.random()*Math.min(r.length,8))].dispatchEvent(new MouseEvent("mouseover",{bubbles:true}));',
            ]
            await page.evaluate(random.choice(actions))
            await asyncio.sleep(self._bp.hover_duration)
        except Exception:
            pass

    async def _simulate_typing(self, page: Any) -> None:
        """Simulate typing into a search input."""
        try:
            search_terms = ["cs2", "na\"vi", "faze", "major", "ranking", "player"]
            term = random.choice(search_terms)
            ms_per_char = 60000 / self._bp.typing_speed_wpm / 5

            await page.evaluate(
                f"(function(){{var e=document.querySelector('input[type=text],input[type=search],[class*=search]');if(e){{e.focus();e.value='{term}';e.dispatchEvent(new Event('input',{{bubbles:true}}));}}}})()"
            )
            await asyncio.sleep(len(term) * (ms_per_char / 1000))
        except Exception:
            pass

    async def _simulate_tab_switch(self, page: Any) -> None:
        """Simulate switching away from and back to the tab."""
        try:
            await page.evaluate(
                "document.dispatchEvent(new Event('visibilitychange'));"
            )
            await asyncio.sleep(self._bp.blur_duration * random.uniform(0.5, 1.5))
            await page.evaluate(
                "document.dispatchEvent(new Event('visibilitychange'));"
            )
        except Exception:
            pass

    async def _dwell_v2(self, page_type: str) -> None:
        """Dwell with per-profile reading speed."""
        if page_type in ("detail",):
            mn, mx = self._s.dwell_detail_min, self._s.dwell_detail_max
        else:
            mn, mx = self._s.dwell_listing_min, self._s.dwell_listing_max

        mu = (mn + mx) / 2
        sigma = (mx - mn) / 4
        dwell = max(0.5, random.gauss(mu, sigma) * self._bp.dwell_multiplier)
        await asyncio.sleep(dwell)

    # ── Warmup paths (backward compat) ──────────

    def get_warmup_paths(self, target_url: str, count: int = 2) -> list[str]:
        """Generate warmup URLs."""
        page_type = self.classify_url(target_url)
        warmup: list[str] = ["https://www.hltv.org/"]
        if count >= 2:
            if page_type == "detail":
                warmup.append(random.choice([
                    "https://www.hltv.org/results",
                    "https://www.hltv.org/matches",
                ]))
            else:
                warmup.append("https://www.hltv.org/matches")
        return warmup[:count]


__all__ = ["HumanBehaviorV2", "BehaviorProfile"]
