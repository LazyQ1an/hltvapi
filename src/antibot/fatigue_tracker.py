"""
IP fatigue tracker — adaptive delay engine for single-IP longevity.

Tracks IP-level metrics (request rate, block rate, response times,
cookie freshness) and computes a fatigue score that drives adaptive
delays. The more fatigued the IP, the longer the delays and more
aggressive the survival strategy.

Fatigue score (0.0 = fresh, 1.0 = exhausted):
  - Request density: how many requests in the last sliding window
  - Block rate: ratio of blocked requests to total
  - Response time trend: increasing response times = fatigue signal
  - Cookie age: older cf_clearance = more likely to be challenged
  - Session duration: longer sessions = higher fatigue

The fatigue score feeds into:
  - AdaptiveRateLimiter delay multiplier
  - Profile rotation urgency
  - Hibernation decisions
"""

from __future__ import annotations

import logging
import time as tmod
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("hltv.antibot.fatigue")


@dataclass
class FatigueMetrics:
    """Rolling window metrics for fatigue calculation."""

    requests: deque[float] = field(default_factory=lambda: deque(maxlen=200))
    blocks: deque[float] = field(default_factory=lambda: deque(maxlen=50))
    response_times: deque[float] = field(default_factory=lambda: deque(maxlen=50))
    cookie_birth_times: dict[str, float] = field(default_factory=dict)
    session_start: float = field(default_factory=tmod.time)


class FatigueTracker:
    """IP-level fatigue engine.

    Usage:
        ft = FatigueTracker(settings)

        # Before each request:
        fatigue = ft.score()
        delay_multiplier = ft.delay_multiplier(fatigue)

        # After each request:
        ft.record_request(response_time=1.2, blocked=False)

        # Check if hibernation needed:
        if ft.should_hibernate():
            await hibernate()
    """

    # Fatigue weights (sum to 1.0)
    _W_REQUEST_DENSITY = 0.25
    _W_BLOCK_RATE = 0.35
    _W_RESPONSE_TREND = 0.20
    _W_COOKIE_AGE = 0.10
    _W_SESSION_DURATION = 0.10

    def __init__(self, settings: Any = None) -> None:
        if settings is None:
            from src.settings import HLTVSettings
            settings = HLTVSettings()
        self._s = settings
        self._m = FatigueMetrics()

        # Hibernation state
        self._hibernating: bool = False
        self._hibernate_until: float = 0.0
        self._hibernate_count: int = 0

        # Baseline response time (for trend detection)
        self._baseline_rt: float = 2.0
        self._baseline_samples: int = 0

        # Daily quota tracking
        self._day_start: float = tmod.time()
        self._requests_today: int = 0

    # ── Core scoring ────────────────────────────

    def score(self) -> float:
        """Compute current fatigue score 0.0 (fresh) to 1.0 (exhausted).

        Weights:
          - Request density (25%): how fast we're hitting HLTV
          - Block rate (35%): most important — blocks = danger
          - Response time trend (20%): slowing responses = pre-block signal
          - Cookie age (10%): stale cf_clearance = challenge risk
          - Session duration (10%): longer sessions = more scrutiny
        """
        now = tmod.time()

        # ── Request density (last 300s window) ──
        recent_reqs = sum(1 for t in self._m.requests if now - t < 300)
        max_safe = self._s.rate_limit.requests_per_hour / 12  # per-5min
        density = min(1.0, recent_reqs / max(max_safe, 1))

        # ── Block rate (last 600s) ──
        recent_blocks = sum(1 for t in self._m.blocks if now - t < 600)
        recent_total = sum(1 for t in self._m.requests if now - t < 600) or 1
        block_rate = recent_blocks / recent_total

        # ── Response time trend ──
        rt_trend = self._compute_rt_trend()

        # ── Cookie age ──
        cookie_age_factor = self._compute_cookie_age_factor(now)

        # ── Session duration ──
        session_hours = (now - self._m.session_start) / 3600
        session_factor = min(1.0, session_hours / 8.0)  # 8h = max

        fatigue = (
            self._W_REQUEST_DENSITY * density +
            self._W_BLOCK_RATE * block_rate +
            self._W_RESPONSE_TREND * rt_trend +
            self._W_COOKIE_AGE * cookie_age_factor +
            self._W_SESSION_DURATION * session_factor
        )

        return round(fatigue, 4)

    def delay_multiplier(self, fatigue: float | None = None) -> float:
        """Convert fatigue score to a delay multiplier.

        Returns 1.0 (normal) to 8.0 (heavily throttled).
        """
        if fatigue is None:
            fatigue = self.score()

        if fatigue < 0.2:
            return 1.0
        elif fatigue < 0.4:
            return 1.0 + (fatigue - 0.2) * 5.0   # 1.0-2.0
        elif fatigue < 0.6:
            return 2.0 + (fatigue - 0.4) * 10.0  # 2.0-4.0
        elif fatigue < 0.8:
            return 4.0 + (fatigue - 0.6) * 10.0  # 4.0-6.0
        else:
            return 6.0 + (fatigue - 0.8) * 10.0  # 6.0-8.0

    # ── Recording ───────────────────────────────

    def record_request(
        self,
        response_time: float = 0.0,
        blocked: bool = False,
    ) -> None:
        """Record a request outcome."""
        now = tmod.time()
        self._m.requests.append(now)
        self._requests_today += 1

        if blocked:
            self._m.blocks.append(now)

        if response_time > 0:
            self._m.response_times.append(response_time)
            self._update_baseline(response_time)

        # Reset daily counter
        if now - self._day_start > 86400:
            self._day_start = now
            self._requests_today = 0

    def record_cookie(self, name: str) -> None:
        """Record when a cookie was harvested."""
        self._m.cookie_birth_times[name] = tmod.time()

    # ── Hibernation ─────────────────────────────

    def should_hibernate(self) -> bool:
        """Check if we should enter hibernation (stop all requests).

        Triggers:
        - Daily quota exhausted (after 8-14h hibernation)
        - Consecutive blocks >= 5
        - Fatigue > 0.9
        """
        now = tmod.time()

        # Already hibernating
        if self._hibernating:
            if now < self._hibernate_until:
                return True
            # Wake up
            self._hibernating = False
            self._reset_session()
            logger.info("Hibernation ended, resuming operations")
            return False

        # Daily quota check
        if self._requests_today >= self._s.rate_limit.requests_per_day:
            self._enter_hibernation("daily_quota")
            return True

        # Consecutive blocks check
        recent_blocks = sum(
            1 for t in self._m.blocks if now - t < 3600
        )
        if recent_blocks >= 5:
            self._enter_hibernation("excessive_blocks")
            return True

        # Fatigue check
        if self.score() > 0.9:
            self._enter_hibernation("extreme_fatigue")
            return True

        return False

    @property
    def hibernation_remaining(self) -> float:
        """Seconds remaining in hibernation (0 if not hibernating)."""
        if not self._hibernating:
            return 0.0
        return max(0.0, self._hibernate_until - tmod.time())

    def _enter_hibernation(self, reason: str) -> None:
        """Enter hibernation for 8-14 hours."""
        import random
        hours = random.uniform(8.0, 14.0)
        self._hibernating = True
        self._hibernate_until = tmod.time() + hours * 3600
        self._hibernate_count += 1
        logger.warning(
            "Entering hibernation (reason=%s, duration=%.1fh, count=%d)",
            reason, hours, self._hibernate_count,
        )

    # ── Internal helpers ────────────────────────

    def _compute_rt_trend(self) -> float:
        """Check if response times are trending up (0=normal, 1=degraded)."""
        rts = list(self._m.response_times)
        if len(rts) < 5 or self._baseline_rt <= 0:
            return 0.0

        recent = rts[-5:]
        avg_recent = sum(recent) / len(recent)
        ratio = avg_recent / self._baseline_rt

        if ratio < 1.2:
            return 0.0
        elif ratio < 2.0:
            return (ratio - 1.2) / 0.8 * 0.5  # 0.0-0.5
        elif ratio < 5.0:
            return 0.5 + (ratio - 2.0) / 3.0 * 0.5  # 0.5-1.0
        else:
            return 1.0

    def _compute_cookie_age_factor(self, now: float) -> float:
        """How stale are our cookies? (0=fresh, 1=expired)."""
        if "cf_clearance" not in self._m.cookie_birth_times:
            return 0.8  # No clearance at all = high risk

        age = now - self._m.cookie_birth_times["cf_clearance"]
        # cf_clearance typically valid 30-60 min
        if age < 900:    # < 15 min
            return 0.0
        elif age < 1800:  # 15-30 min
            return (age - 900) / 900 * 0.3
        elif age < 3600:  # 30-60 min
            return 0.3 + (age - 1800) / 1800 * 0.5
        else:
            return 0.8 + min(0.2, (age - 3600) / 7200 * 0.2)

    def _update_baseline(self, rt: float) -> None:
        """Update the baseline response time estimate."""
        if self._baseline_samples < 10:
            self._baseline_samples += 1
            self._baseline_rt = (
                (self._baseline_rt * (self._baseline_samples - 1) + rt)
                / self._baseline_samples
            )
        else:
            # Exponential moving average
            self._baseline_rt = self._baseline_rt * 0.95 + rt * 0.05

    def _reset_session(self) -> None:
        """Reset session tracking after hibernation."""
        self._m.session_start = tmod.time()
        self._m.requests.clear()
        self._m.blocks.clear()

    def get_stats(self) -> dict[str, Any]:
        """Return fatigue statistics for monitoring."""
        now = tmod.time()
        recent_reqs = sum(1 for t in self._m.requests if now - t < 300)
        recent_blocks = sum(1 for t in self._m.blocks if now - t < 600)
        return {
            "fatigue_score": self.score(),
            "delay_multiplier": self.delay_multiplier(),
            "requests_last_5min": recent_reqs,
            "blocks_last_10min": recent_blocks,
            "requests_today": self._requests_today,
            "daily_quota": self._s.rate_limit.requests_per_day,
            "baseline_rt": round(self._baseline_rt, 2),
            "hibernating": self._hibernating,
            "hibernation_remaining_s": int(self.hibernation_remaining),
            "hibernation_count": self._hibernate_count,
            "session_hours": round((now - self._m.session_start) / 3600, 1),
            "has_cf_clearance": "cf_clearance" in self._m.cookie_birth_times,
        }


__all__ = ["FatigueTracker", "FatigueMetrics"]
