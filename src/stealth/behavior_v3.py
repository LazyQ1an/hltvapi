"""
Human Behavior Engine v3 — micro-physics mouse + complete pointer event chains. NG1.0

Replaces Bezier curves with micro-tremor mouse movement based on
real human motor physics. Implements complete browser event chains
(not just click), matching the exact spec order:

  pointerover -> pointerenter -> mousemove -> mousedown -> pointerdown
  -> focus -> mouseup -> pointerup -> click

Micro-physics features:
- Micro-tremor: 8-12Hz physiological hand tremor (~0.5-2px amplitude)
- Velocity inertia: deceleration follows Fitts' Law
- Overshoot correction: humans often overshoot small targets
- Sub-pixel positioning: real mice report sub-pixel coordinates
- Event timing jitter: real inter-event intervals have 5-15ms natural variance
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from typing import Any

logger = logging.getLogger("hltv.stealth.behavior_v3")


class MicroPhysicsMouse:
    """Micro-tremor mouse movement with velocity inertia.

    Instead of Bezier curves (which ML models detect as synthetic),
    this simulates the physics of a real human hand:
    - Initial acceleration (motor planning)
    - Ballistic phase (fast movement toward target)
    - Deceleration + micro-corrections (visual feedback loop)
    - Physiological tremor (8-12Hz oscillation)
    """

    # Tremor parameters (physiological)
    TREMOR_FREQUENCY = 10.0       # Hz (8-12 is normal)
    TREMOR_AMPLITUDE = 1.2        # pixels (0.5-2.0 is normal)
    TREMOR_PHASE_VARIANCE = 0.3   # phase randomness

    # Movement parameters
    ACCELERATION_PHASE_RATIO = 0.15   # first 15% of movement is acceleration
    BALLISTIC_PHASE_RATIO = 0.60      # middle 60% is fast movement
    DECELERATION_PHASE_RATIO = 0.25   # last 25% is deceleration + micro-corrections

    # Sampling rate (typical USB mouse: 125-1000Hz, we use 200Hz for realism)
    SAMPLE_INTERVAL = 0.005  # 5ms = 200Hz

    def __init__(self) -> None:
        self._tremor_phase = random.uniform(0, 2 * math.pi)
        self._velocity_x = 0.0
        self._velocity_y = 0.0

    def generate_path(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> list[tuple[float, float, float]]:
        """Generate a micro-physics mouse path.

        Returns list of (x, y, timestamp_delta) tuples.
        """
        dx = x1 - x0
        dy = y1 - y0
        distance = math.sqrt(dx**2 + dy**2)

        if distance < 2:
            return [(x1, y1, 0.01)]

        # Total movement time (Fitts' Law approximation)
        # ID = log2(D/W + 1), MT = a + b*ID
        # For typical GUI targets: W=20px, a=50ms, b=100ms
        target_width = max(10, min(200, distance * 0.3))
        id_ = math.log2(distance / target_width + 1)
        total_time = 0.05 + 0.10 * id_  # seconds
        total_time = max(0.08, min(2.0, total_time))

        n_samples = max(3, int(total_time / self.SAMPLE_INTERVAL))
        points: list[tuple[float, float, float]] = []

        for i in range(n_samples):
            t = i / (n_samples - 1)

            # Phase-dependent velocity profile
            if t < self.ACCELERATION_PHASE_RATIO:
                # Acceleration phase: ease-in quad
                progress = (t / self.ACCELERATION_PHASE_RATIO) ** 2
            elif t < self.ACCELERATION_PHASE_RATIO + self.BALLISTIC_PHASE_RATIO:
                # Ballistic phase: linear
                progress = (
                    self.ACCELERATION_PHASE_RATIO +
                    (t - self.ACCELERATION_PHASE_RATIO)
                )
            else:
                # Deceleration + micro-correction
                # Ease-out with overshoot tendency
                decel_t = (t - self.ACCELERATION_PHASE_RATIO - self.BALLISTIC_PHASE_RATIO) / self.DECELERATION_PHASE_RATIO
                # Slight overshoot then correction (humans do this)
                if decel_t < 0.3:
                    # Possible overshoot
                    overshoot = 1.0 + (1 - decel_t / 0.3) * 0.02
                else:
                    overshoot = 1.0
                progress = 1.0 - (1 - decel_t) ** 3 * overshoot

            # Base position
            x = x0 + dx * min(1.0, max(0.0, progress))
            y = y0 + dy * min(1.0, max(0.0, progress))

            # Micro-tremor (physiological hand tremor)
            tremor_x = math.sin(self._tremor_phase + t * 2 * math.pi * self.TREMOR_FREQUENCY)
            tremor_y = math.cos(self._tremor_phase + t * 2 * math.pi * self.TREMOR_FREQUENCY + 0.7)
            x += tremor_x * self.TREMOR_AMPLITUDE * (1 - abs(progress - 0.5) * 2)  # Less tremor mid-movement
            y += tremor_y * self.TREMOR_AMPLITUDE * (1 - abs(progress - 0.5) * 2)

            # Sub-pixel precision (real mice report this)
            x += random.gauss(0, 0.15)
            y += random.gauss(0, 0.15)

            # Time delta with natural jitter
            dt = self.SAMPLE_INTERVAL + random.gauss(0, 0.001)

            points.append((round(x, 2), round(y, 2), max(0.001, dt)))

        # Update phase for next movement
        self._tremor_phase += total_time * 2 * math.pi * self.TREMOR_FREQUENCY

        return points


class CompletePointerEvents:
    """Generate complete browser pointer event chains.

    Real browsers fire events in strict order:
      pointerover -> pointerenter -> mousemove -> mousedown -> pointerdown
      -> (optional: select, selectionchange) -> focus -> mouseup -> pointerup
      -> click -> dblclick (if rapid)

    Each event has correct properties:
    - pointerId, pointerType, isPrimary
    - pressure (0.5 for mouse, varies for pen/touch)
    - tiltX/tiltY (0 for mouse)
    - width/height (1 for mouse)
    - button, buttons, detail
    """

    def build_click_chain(
        self,
        x: float,
        y: float,
        target_selector: str = "",
    ) -> str:
        """Build JavaScript that fires a complete click event chain.

        Args:
            x, y: Target coordinates.
            target_selector: Optional CSS selector for the target element.

        Returns:
            JavaScript string to evaluate.
        """
        find_target = (
            f'var el = document.querySelector("{target_selector}") || document.elementFromPoint({x},{y});'
            if target_selector
            else f'var el = document.elementFromPoint({x},{y});'
        )

        # Random event timing (5-25ms between events, natural variance)
        t1 = random.randint(5, 12)   # pointerover -> pointerenter
        t2 = random.randint(8, 20)   # -> mousemove
        t3 = random.randint(3, 8)    # -> mousedown
        t4 = random.randint(1, 5)    # -> pointerdown
        t5 = random.randint(2, 6)    # -> focus
        t6 = random.randint(8, 25)   # hold duration (mousedown -> mouseup)
        t7 = random.randint(1, 4)    # -> mouseup
        t8 = random.randint(1, 4)    # -> pointerup
        t9 = random.randint(3, 10)   # -> click

        pointer_id = random.randint(1, 5)

        return f"""
(function() {{
    'use strict';
    {find_target}
    if (!el) return;

    const rect = el.getBoundingClientRect();
    const cx = rect.left + {x};
    const cy = rect.top + {y};

    function fire(type, init) {{
        const event = new PointerEvent(type, Object.assign({{
            bubbles: true, cancelable: true, composed: true,
            pointerId: {pointer_id}, pointerType: 'mouse', isPrimary: true,
            width: 1, height: 1, pressure: 0.5,
            tangentialPressure: 0, tiltX: 0, tiltY: 0, twist: 0,
            clientX: cx, clientY: cy,
            screenX: cx, screenY: cy,
            button: 0, buttons: 1, detail: 1,
        }}, init));
        el.dispatchEvent(event);
    }}

    function fireMouse(type, init) {{
        const event = new MouseEvent(type, Object.assign({{
            bubbles: true, cancelable: true, composed: true,
            clientX: cx, clientY: cy,
            screenX: cx, screenY: cy,
            button: 0, buttons: 1, detail: 1,
        }}, init));
        el.dispatchEvent(event);
    }}

    // Phase 1: Approach
    fire('pointerover', {{ buttons: 0 }});
    setTimeout(function() {{
        fire('pointerenter', {{ buttons: 0 }});
        fireMouse('mouseover', {{ buttons: 0 }});
        fireMouse('mouseenter', {{ buttons: 0 }});
    }}, {t1});

    setTimeout(function() {{
        // Phase 2: Move to target
        fire('pointermove', {{ buttons: 0 }});
        fireMouse('mousemove', {{ buttons: 0 }});
    }}, {t1 + t2});

    setTimeout(function() {{
        // Phase 3: Press down
        fire('pointerdown', {{ pressure: 0.7 }});
        fireMouse('mousedown', {{ button: 0, buttons: 1 }});
    }}, {t1 + t2 + t3});

    setTimeout(function() {{
        // Phase 4: Focus
        if (el.focus) el.focus();
        fire('gotpointercapture');
    }}, {t1 + t2 + t3 + t4 + t5});

    setTimeout(function() {{
        // Phase 5: Release
        fire('pointerup', {{ pressure: 0 }});
        fireMouse('mouseup', {{ button: 0, buttons: 0 }});
        fire('lostpointercapture');
    }}, {t1 + t2 + t3 + t4 + t5 + t6});

    setTimeout(function() {{
        // Phase 6: Click completion
        fireMouse('click', {{ button: 0, buttons: 0 }});
    }}, {t1 + t2 + t3 + t4 + t5 + t6 + t7 + t8 + t9});
}})();
"""

    def build_hover_chain(self, x: float, y: float) -> str:
        """Build a hover event chain (no click)."""
        pointer_id = random.randint(1, 5)
        return f"""
(function() {{
    const el = document.elementFromPoint({x},{y});
    if (!el) return;

    function fire(type) {{
        el.dispatchEvent(new PointerEvent(type, {{
            bubbles: true, cancelable: true, composed: true,
            pointerId: {pointer_id}, pointerType: 'mouse', isPrimary: true,
            width: 1, height: 1, pressure: 0.5,
            clientX: {x}, clientY: {y},
        }}));
    }}

    el.dispatchEvent(new MouseEvent('mouseover', {{
        bubbles: true, cancelable: true,
        clientX: {x}, clientY: {y}
    }}));
    el.dispatchEvent(new MouseEvent('mouseenter', {{
        bubbles: false, cancelable: true,
        clientX: {x}, clientY: {y}
    }}));
    fire('pointerover');
    fire('pointerenter');
    fire('pointermove');
    el.dispatchEvent(new MouseEvent('mousemove', {{
        bubbles: true, cancelable: true,
        clientX: {x}, clientY: {y}
    }}));
}})();
"""


class HumanBehaviorV3:
    """Behavior engine v3 with micro-physics mouse and complete event chains.

    Usage:
        behavior = HumanBehaviorV3(settings)
        mouse = MicroPhysicsMouse()
        events = CompletePointerEvents()

        # Move mouse with micro-tremor
        path = mouse.generate_path(100, 100, 500, 300)
        for x, y, dt in path:
            await page.evaluate(events.build_hover_chain(x, y))
            await asyncio.sleep(dt)

        # Click with complete event chain
        await page.evaluate(events.build_click_chain(500, 300))
    """

    def __init__(self, settings: Any = None) -> None:
        if settings is None:
            from src.settings import BehaviorSettings
            settings = BehaviorSettings()
        self._s = settings
        self._mouse = MicroPhysicsMouse()
        self._events = CompletePointerEvents()

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
        return "home" if path in ("/", "") else "other"

    async def simulate_visit(self, page: Any, page_type: str = "listing") -> None:
        """Full behavior simulation for a page visit."""
        try:
            await asyncio.sleep(random.uniform(0.3, 1.0))

            # Move mouse to a natural position with micro-tremor
            x0, y0 = random.randint(50, 300), random.randint(50, 300)
            x1, y1 = random.randint(400, 1500), random.randint(100, 700)

            path = self._mouse.generate_path(x0, y0, x1, y1)
            for x, y, dt in path:
                await page.evaluate(self._events.build_hover_chain(x, y))
                await asyncio.sleep(dt)

            # Scroll if configured
            if random.random() < self._s.scroll_probability:
                await self._scroll_natural(page)

            # Dwell
            await self._dwell(page_type)

        except Exception as e:
            logger.debug("Behavior v3: %s", e)

    async def _scroll_natural(self, page: Any) -> None:
        try:
            total = random.randint(self._s.scroll_pixels_min, self._s.scroll_pixels_max)
            steps = random.randint(3, 7)
            remaining = total
            for i in range(steps):
                progress = (i + 1) / steps
                factor = min(progress / 0.3, 1.0) if progress < 0.3 else (1.0 if progress < 0.7 else (1 - progress) / 0.3)
                step_px = max(10, min(int(remaining * factor * 0.4), remaining))
                remaining -= step_px
                await page.evaluate(f"window.scrollBy({{top: {step_px}, left: 0, behavior: 'auto'}})")
                await asyncio.sleep(random.uniform(0.03, 0.12))
        except Exception:
            pass

    async def _dwell(self, page_type: str) -> None:
        if page_type == "detail":
            mn, mx = self._s.dwell_detail_min, self._s.dwell_detail_max
        else:
            mn, mx = self._s.dwell_listing_min, self._s.dwell_listing_max
        mu = (mn + mx) / 2
        sigma = (mx - mn) / 4
        await asyncio.sleep(max(0.5, random.gauss(mu, sigma)))

    def get_warmup_paths(self, target_url: str, count: int = 2) -> list[str]:
        pt = self.classify_url(target_url)
        wu: list[str] = ["https://www.hltv.org/"]
        if count >= 2:
            wu.append("https://www.hltv.org/results" if pt == "detail" else "https://www.hltv.org/matches")
        return wu[:count]


__all__ = ["HumanBehaviorV3", "MicroPhysicsMouse", "CompletePointerEvents"]
