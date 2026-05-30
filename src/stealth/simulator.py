"""
Lightweight human behavior simulator for server environments. NG1.0

Enhanced with:
- Browse trajectory simulation (home -> listing -> detail -> back)
- Natural mouse movement curves (bezier-style multi-point paths)
- Realistic scroll velocity profiles
- Light interaction simulation (search hover, non-critical clicks)
- Variable dwell time distributions (log-normal, not uniform)

Designed for long-running server processes: all operations are
non-blocking, resource-light, and skip probabilistically.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

logger = logging.getLogger("hltv.stealth.simulator")


class HumanBehaviorSimulator:
    """Lightweight, async human-like behavior for Nodriver pages.

    Usage:
        sim = HumanBehaviorSimulator(settings)
        await sim.simulate_visit(page, "match_detail")
    """

    def __init__(self, settings: Any = None) -> None:
        if settings is None:
            from src.settings import BehaviorSettings
            settings = BehaviorSettings()
        self._s = settings
        self._trajectory_state: dict[str, Any] = {
            "visited": [],
            "current": "home",
        }

    def classify_url(self, url: str) -> str:
        """Classify a URL into a page type for behavior tuning."""
        path = url.lower()
        if "/search" in path:
            return "search"
        if "/matches/" in path and path.count("/") > 3:
            return "detail"
        if "/results/" in path and path.count("/") > 3:
            return "detail"
        if "/team/" in path:
            return "detail"
        if "/player/" in path:
            return "detail"
        if "/news/" in path and path.count("/") > 3:
            return "detail"
        if "/events/" in path and path.count("/") > 3:
            return "detail"
        if any(p in path for p in ("/matches", "/results", "/ranking", "/events", "/stats")):
            return "listing"
        if path in ("/", "", "/hltv"):
            return "home"
        return "other"

    async def simulate_visit(self, page: Any, page_type: str = "listing") -> None:
        """Run a lightweight behavior simulation.

        Sequence:
        1. Brief initial pause (page rendering)
        2. Mouse movement (bezier curve)
        3. Scroll (probabilistic, natural velocity)
        4. Light interaction (probabilistic)
        5. Dwell time (log-normal distribution)
        """
        try:
            # 1. Initial pause
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # 2. Mouse movement (bezier curve)
            if self._s.mouse_move_count > 0:
                for _ in range(self._s.mouse_move_count):
                    await self._move_mouse_curve(page)
                    await asyncio.sleep(random.uniform(0.15, 0.4))

            # 3. Scroll
            if random.random() < self._s.scroll_probability:
                await self._scroll_natural(page)

            # 4. Light interaction
            if random.random() < self._s.interaction_probability:
                await self._light_interact(page, page_type)

            # 5. Dwell
            await self._dwell(page_type)

        except Exception as e:
            logger.debug("Behavior simulation: %s", e)

    # ── Mouse curve ─────────────────────────────

    async def _move_mouse_curve(self, page: Any) -> None:
        """Move mouse along a natural bezier curve.

        Real mouse movements are not straight lines. We generate
        a cubic bezier with random control points and move through
        intermediate steps.
        """
        try:
            n = self._s.mouse_curve_points
            x0, y0 = random.randint(50, 300), random.randint(50, 300)
            x3, y3 = random.randint(400, 1500), random.randint(100, 700)
            x1 = x0 + random.randint(-200, 400)
            y1 = y0 + random.randint(-200, 200)
            x2 = x3 + random.randint(-400, 200)
            y2 = y3 + random.randint(-200, 200)

            for i in range(n + 1):
                t = i / n
                # Cubic bezier
                u = 1 - t
                x = int(u**3 * x0 + 3 * u**2 * t * x1 + 3 * u * t**2 * x2 + t**3 * x3)
                y = int(u**3 * y0 + 3 * u**2 * t * y1 + 3 * u * t**2 * y2 + t**3 * y3)

                await page.evaluate(
                    f"""
                    (function() {{
                        const el = document.elementFromPoint({x}, {y});
                        if (el) {{
                            el.dispatchEvent(new MouseEvent('mousemove', {{
                                clientX: {x}, clientY: {y}, bubbles: true
                            }}));
                        }}
                    }})()
                    """
                )
                # Realistic per-point delay
                await asyncio.sleep(random.uniform(0.005, 0.03))
        except Exception:
            pass

    # ── Natural scroll ──────────────────────────

    async def _scroll_natural(self, page: Any) -> None:
        """Scroll with natural velocity profile.

        Real scrolling has acceleration and deceleration phases.
        We simulate this with multiple scrollBy calls at varying distances.
        """
        try:
            total = random.randint(
                self._s.scroll_pixels_min,
                self._s.scroll_pixels_max,
            )
            steps = random.randint(3, 6)
            remaining = total

            for i in range(steps):
                # Accelerate then decelerate
                progress = (i + 1) / steps
                if progress < 0.3:
                    factor = progress / 0.3  # 0 -> 1
                elif progress > 0.7:
                    factor = (1.0 - progress) / 0.3  # 1 -> 0
                else:
                    factor = 1.0

                step_px = int(remaining * factor * 0.4)
                step_px = max(20, min(step_px, remaining))
                remaining -= step_px

                await page.evaluate(
                    f"window.scrollBy({{top: {step_px}, left: 0, behavior: 'auto'}})"
                )
                await asyncio.sleep(random.uniform(0.03, 0.12))
        except Exception:
            pass

    # ── Light interaction ───────────────────────

    async def _light_interact(self, page: Any, page_type: str) -> None:
        """Simulate a light user interaction.

        On listing pages: hover over a result row.
        On detail pages: hover over a stat or tab.
        Occasionally: hover over search bar.
        """
        try:
            actions = [
                # Hover search icon
                'const el = document.querySelector("[class*=search], [id*=search], input[type=text]"); if(el) { el.dispatchEvent(new MouseEvent("mouseover", {bubbles:true})); }',
                # Hover nav item
                'const links = document.querySelectorAll("a[href]"); if(links.length>3) { links[Math.floor(Math.random()*Math.min(links.length,10))].dispatchEvent(new MouseEvent("mouseover", {bubbles:true})); }',
                # Hover a table row
                'const rows = document.querySelectorAll("tr, .result, .match, [class*=row]"); if(rows.length>1) { rows[Math.floor(Math.random()*Math.min(rows.length,8))].dispatchEvent(new MouseEvent("mouseover", {bubbles:true})); }',
            ]
            await page.evaluate(random.choice(actions))
            await asyncio.sleep(random.uniform(0.3, 0.8))
        except Exception:
            pass

    # ── Dwell ───────────────────────────────────

    async def _dwell(self, page_type: str) -> None:
        """Wait with a log-normal-like distribution.

        Real reading times follow roughly log-normal distributions,
        not uniform. We approximate with a clamped normal.
        """
        if page_type in ("detail",):
            mu = (self._s.dwell_detail_min + self._s.dwell_detail_max) / 2
            sigma = (self._s.dwell_detail_max - self._s.dwell_detail_min) / 4
        else:
            mu = (self._s.dwell_listing_min + self._s.dwell_listing_max) / 2
            sigma = (self._s.dwell_listing_max - self._s.dwell_listing_min) / 4

        dwell = max(1.0, random.gauss(mu, sigma))
        await asyncio.sleep(dwell)

    # ── Browse trajectory ───────────────────────

    def get_trajectory(self, target_url: str) -> list[str]:
        """Generate a natural browse trajectory.

        Pattern: homepage -> listing page -> target detail page

        Args:
            target_url: The ultimate destination.

        Returns:
            Ordered list of URLs forming a natural browsing path.
        """
        page_type = self.classify_url(target_url)
        trajectory: list[str] = []

        # 1. Start at homepage
        trajectory.append("https://www.hltv.org/")

        # 2. Navigate to a listing
        if page_type == "detail":
            listing = random.choice([
                "https://www.hltv.org/results",
                "https://www.hltv.org/matches",
            ])
            trajectory.append(listing)

        elif page_type == "listing":
            # Already at a listing, but come from a different one
            trajectory.append("https://www.hltv.org/")

        # 3. Target page is visited by caller after warmup

        self._trajectory_state["visited"] = trajectory
        self._trajectory_state["current"] = page_type

        return trajectory

    def get_warmup_paths(self, target_url: str, count: int = 2) -> list[str]:
        """Generate warmup URLs (backward compat)."""
        if self._s.browse_trajectory:
            return self.get_trajectory(target_url)[:count]

        count = max(1, min(count, 3))
        warmup: list[str] = ["https://www.hltv.org/"]
        if count >= 2:
            warmup.append("https://www.hltv.org/results")
        return warmup[:count]


__all__ = ["HumanBehaviorSimulator"]
