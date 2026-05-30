"""
Purposeless browsing injection — insert "idle human" behaviour between
target data pages to wash the request stream. NG1.0

Real HLTV users don't navigate player → player → player → player
in rapid succession. They:
- Check the frontpage live scores
- Browse a news article
- Scroll the upcoming matches list without clicking
- Open the rankings page, glance at top 5, leave
- Pause to read something, then resume

By inserting these high-trust, low-value interactions between target
requests, the session's overall semantic score stays in human territory.
Cloudflare's behavioural models see: "household sports fan" not "scraper".

Strategy:
- Every N target requests, inject a "purposeless" path
- Paths are predefined high-trust HLTV URLs with minimal parsing cost
- Dwell times use content-driven timing for coherence
- Some paths are "dead ends" (view only, no data extraction)
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Callable, Awaitable

logger = logging.getLogger("hltv.stealth.purposeless")


# ---------------------------------------------------------------------------
# Predefined browsing paths
# ---------------------------------------------------------------------------

@dataclass
class BrowsingPath:
    """A predefined sequence of (url, dwell_type, weight) tuples."""
    name: str
    steps: list[tuple[str, str, float]]  # (relative_url, page_type, base_weight)
    description: str = ""


# High-trust, low-risk HLTV paths
_HLTV_PATHS: list[BrowsingPath] = [
    BrowsingPath(
        name="homepage_glance",
        description="Open homepage, glance at live scores, leave",
        steps=[
            ("/", "listing", 0.6),
        ],
    ),
    BrowsingPath(
        name="casual_news",
        description="Browse homepage → open one news article → return",
        steps=[
            ("/", "listing", 0.4),
            ("/news", "listing", 0.7),
        ],
    ),
    BrowsingPath(
        name="ranking_skim",
        description="Open rankings, skim top teams, scroll a bit",
        steps=[
            ("/ranking", "listing", 0.8),
        ],
    ),
    BrowsingPath(
        name="upcoming_scroll",
        description="Browse upcoming matches, scroll without clicking",
        steps=[
            ("/matches", "listing", 0.7),
        ],
    ),
    BrowsingPath(
        name="results_glance",
        description="Check latest results, maybe open one",
        steps=[
            ("/results", "listing", 0.75),
        ],
    ),
    BrowsingPath(
        name="stats_overview",
        description="Open stats overview, glance, leave",
        steps=[
            ("/stats", "listing", 0.6),
        ],
    ),
    BrowsingPath(
        name="multi_tab_wander",
        description="Homepage → upcoming → a specific event → back",
        steps=[
            ("/", "listing", 0.35),
            ("/matches", "listing", 0.45),
            ("/events", "listing", 0.6),
        ],
    ),
    BrowsingPath(
        name="deep_idle",
        description="News page → scroll → long pause like reading",
        steps=[
            ("/news", "detail", 1.2),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Purposeless browsing engine
# ---------------------------------------------------------------------------

class PurposelessBrowsingEngine:
    """Insert "useless" human browsing between target requests.

    Usage:
        engine = PurposelessBrowsingEngine(client.get)

        for url in target_urls:
            data = await client.get(url)
            # ... extract data ...

            # Every 3-7 target requests, insert noise
            if engine.should_browse():
                await engine.inject_browsing_session()

    Configuration:
        interval_min / interval_max: how many target requests between noise
        path_count: how many paths to inject per session (1-3)
        dwell_factor: multiplier on content-driven timing (0.5=fast, 1.5=slow)
    """

    def __init__(
        self,
        interval_min: int = 3,
        interval_max: int = 8,
        path_count_min: int = 1,
        path_count_max: int = 2,
        dwell_factor: float = 0.7,  # purposeless browsing is faster than real reading
    ) -> None:
        self._interval_min = interval_min
        self._interval_max = interval_max
        self._path_count_min = path_count_min
        self._path_count_max = path_count_max
        self._dwell_factor = dwell_factor

        self._request_count: int = 0
        self._next_injection_at: int = self._random_interval()
        self._browse_history: list[str] = []  # paths already taken recently
        self._base_url: str = "https://www.hltv.org"

    def _random_interval(self) -> int:
        return random.randint(self._interval_min, self._interval_max)

    def should_browse(self) -> bool:
        """Check if we should inject a purposeless browsing session now."""
        self._request_count += 1
        if self._request_count >= self._next_injection_at:
            self._request_count = 0
            self._next_injection_at = self._random_interval()
            return True
        return False

    def _select_paths(self) -> list[BrowsingPath]:
        """Select 1-2 paths, avoiding recent repeats."""
        count = random.randint(self._path_count_min, self._path_count_max)
        available = [p for p in _HLTV_PATHS if p.name not in self._browse_history[-4:]]
        if not available:
            available = list(_HLTV_PATHS)
        selected = random.sample(available, min(count, len(available)))
        for p in selected:
            self._browse_history.append(p.name)
        if len(self._browse_history) > 20:
            self._browse_history = self._browse_history[-10:]
        return selected

    async def inject_browsing_session(
        self,
        fetch_fn: Callable[[str], Awaitable[str]] | None = None,
        base_url: str = "https://www.hltv.org",
    ) -> list[str]:
        """Execute a purposeless browsing session.

        Args:
            fetch_fn: Async function that takes URL and returns HTML.
            base_url: Base HLTV URL.

        Returns:
            List of URLs visited during the session.
        """
        self._base_url = base_url
        paths = self._select_paths()
        visited: list[str] = []

        if not fetch_fn:
            logger.debug("Purposeless browse skipped (no fetch_fn provided)")
            return visited

        logger.info("Injecting purposeless browsing: %d path(s)", len(paths))

        for path in paths:
            for step_url, page_type, weight in path.steps:
                full_url = f"{base_url.rstrip('/')}{step_url}"
                try:
                    # Small random pause between steps (human transition time)
                    await asyncio.sleep(random.uniform(1.0, 4.0) * self._dwell_factor)

                    _html = await fetch_fn(full_url)
                    visited.append(full_url)

                    # Dwell proportional to page type and weight
                    dwell = {
                        "listing": random.uniform(2.0, 6.0),
                        "detail": random.uniform(5.0, 18.0),
                        "stats": random.uniform(3.0, 10.0),
                    }.get(page_type, 3.0) * weight * self._dwell_factor

                    logger.debug("Purposeless dwell: %.1fs on %s (%s)", dwell, step_url, path.name)
                    await asyncio.sleep(dwell)

                except Exception as e:
                    logger.debug("Purposeless browse error on %s: %s", full_url, e)
                    # Don't fail the whole session for one noise URL
                    continue

        return visited

    def reset(self) -> None:
        """Reset injection counter (e.g., after a long pause)."""
        self._request_count = 0
        self._next_injection_at = self._random_interval()


# ---------------------------------------------------------------------------
# Idle session simulator
# ---------------------------------------------------------------------------

class IdleSessionSimulator:
    """Simulate a user who opens HLTV and does... not much.

    Models the behaviour of someone who:
    - Opens the site to "check scores"
    - Scrolls a bit
    - Maybe opens one interesting link
    - Gets distracted by something else
    - Comes back a few minutes later

    Useful for Profile warmup and re-warming after challenges.
    """

    def __init__(self, base_url: str = "https://www.hltv.org") -> None:
        self._base_url = base_url

    async def simulate_idle_arrival(
        self,
        fetch_fn: Callable[[str], Awaitable[str]],
        duration_seconds: float = 45.0,
    ) -> list[str]:
        """Simulate a casual arrival on the site.

        The user opens HLTV, glances at the homepage, maybe clicks
        one thing, then sits idle for a while.

        Args:
            fetch_fn: Async fetch function.
            duration_seconds: Total session duration to simulate.

        Returns:
            URLs visited.
        """
        visited: list[str] = []
        elapsed = 0.0

        # Step 1: Arrive at homepage
        try:
            await fetch_fn(self._base_url + "/")
            visited.append(self._base_url + "/")
            await asyncio.sleep(random.uniform(3.0, 7.0))
            elapsed += 7.0
        except Exception:
            return visited

        # Step 2: Maybe scroll upcoming matches (no fetch needed, just dwell)
        if elapsed < duration_seconds:
            await asyncio.sleep(random.uniform(2.0, 5.0))
            elapsed += 5.0

        # Step 3: Maybe browse one section (50% chance)
        if elapsed < duration_seconds and random.random() < 0.5:
            section = random.choice(["/matches", "/results", "/news", "/ranking"])
            try:
                await fetch_fn(self._base_url + section)
                visited.append(self._base_url + section)
                await asyncio.sleep(random.uniform(4.0, 10.0))
                elapsed += 10.0
            except Exception:
                pass

        # Step 4: Idle the remaining time
        remaining = duration_seconds - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

        logger.debug("Idle arrival simulation: %d URLs over %.0fs", len(visited), duration_seconds)
        return visited


__all__ = [
    "BrowsingPath",
    "PurposelessBrowsingEngine",
    "IdleSessionSimulator",
]
