"""
Adaptive Survival Brain — priority-aware request scheduling for single-IP longevity. NG1.0

Components:
1. PriorityQueue — ordered request executor with deadline awareness
2. PredictiveDelay — time-of-day + fatigue + history-aware delay calculator
3. DualRateLimiter — global + per-profile rate limits
4. ContentChangeDetector — content hash comparison for incremental crawling

Design philosophy: every parameter adapts in real-time based on IP fatigue,
time of day, block history, and profile health. The brain makes all
scheduling decisions autonomously.
"""

from __future__ import annotations

import hashlib
import heapq
import logging
import time as tmod
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("hltv.core.brain")


# ── Priority Request ───────────────────────────

@dataclass(order=True)
class PriorityRequest:
    """A request with scheduling priority.

    Lower priority number = earlier execution.
    Priority is computed from: request type weight + deadline pressure.
    """

    priority: int
    url: str = field(compare=False)
    request_type: str = field(compare=False)  # listing, detail, search, etc.
    deadline: float = field(compare=False)
    created_at: float = field(default_factory=tmod.time, compare=False)
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)


# ── Content Change Detector ────────────────────

class ContentChangeDetector:
    """Detect whether page content has changed since last fetch.

    Uses content hash (blake2b) comparison. If content hasn't changed,
    we can skip re-parsing and save CPU. If ETag/Last-Modified are
    available, they're preferred over hash comparison.
    """

    def __init__(self, max_entries: int = 1000) -> None:
        self._hashes: dict[str, str] = {}
        self._timestamps: dict[str, float] = {}
        self._max = max_entries

    def has_changed(self, url: str, content: str) -> bool:
        """Check if content has changed from last known state.

        Returns True if content is new or different, False if identical.
        """
        if not content:
            return True

        new_hash = hashlib.blake2b(
            content.encode("utf-8"), digest_size=16
        ).hexdigest()

        old_hash = self._hashes.get(url)
        self._hashes[url] = new_hash
        self._timestamps[url] = tmod.time()

        # Trim cache
        if len(self._hashes) > self._max:
            oldest = sorted(self._timestamps, key=lambda k: self._timestamps[k])
            for k in oldest[:len(self._hashes) - self._max]:
                self._hashes.pop(k, None)
                self._timestamps.pop(k, None)

        return old_hash != new_hash

    def get_hash(self, url: str) -> str | None:
        return self._hashes.get(url)


# ── Predictive Delay Calculator ────────────────

class PredictiveDelay:
    """Calculate optimal delay before next request.

    Factors:
    - Base delay (from settings)
    - IP fatigue multiplier
    - Time-of-day factor (off-peak = faster, peak = slower)
    - Block history decay
    - Request type weight (detail pages need more delay)
    - Profile health factor
    - Success streak bonus (recent successes = slightly faster)
    """

    def __init__(self, settings: Any = None) -> None:
        if settings is None:
            from src.settings import RateLimitSettings
            settings = RateLimitSettings()
        self._s = settings
        self._recent_successes: deque[float] = deque(maxlen=20)
        self._recent_blocks: deque[float] = deque(maxlen=10)

    def compute(
        self,
        *,
        fatigue_score: float = 0.0,
        request_type: str = "listing",
        profile_health: float = 1.0,
    ) -> float:
        """Compute optimal delay in seconds."""
        import random

        # Base delay
        base = random.uniform(self._s.min_delay, self._s.max_delay)

        # Jitter
        if self._s.jitter:
            base += random.gauss(0, base * 0.2)

        # Fatigue scaling (0.0→1.0x, 1.0→8.0x)
        fatigue_mult = 1.0 + fatigue_score * 7.0

        # Time of day factor
        tod = self._time_of_day_factor()

        # Request type weight
        type_w = self._type_weight(request_type)

        # Profile health (healthier = faster)
        health_w = max(0.5, 2.0 - profile_health * 1.5)

        # Block penalty (recent blocks slow us down)
        now = tmod.time()
        recent_b = sum(1 for t in self._recent_blocks if now - t < 600)
        block_penalty = 1.0 + recent_b * 0.5

        # Success bonus (recent successes speed us up slightly)
        recent_s = sum(1 for t in self._recent_successes if now - t < 300)
        success_bonus = max(0.7, 1.0 - recent_s * 0.05)

        delay = base * fatigue_mult * tod * type_w * health_w * block_penalty * success_bonus

        return max(0.5, delay)

    def record_success(self) -> None:
        self._recent_successes.append(tmod.time())

    def record_block(self) -> None:
        self._recent_blocks.append(tmod.time())

    def _time_of_day_factor(self) -> float:
        """Return multiplier based on current hour.

        Peak hours (when real users browse) = slower (1.0-1.3x).
        Off-peak (night) = faster (0.7-0.9x).
        """
        hour = tmod.localtime().tm_hour
        if 8 <= hour <= 10:    # Morning peak
            return 1.2
        elif 11 <= hour <= 13:  # Lunch
            return 1.0
        elif 14 <= hour <= 17:  # Afternoon
            return 1.1
        elif 18 <= hour <= 22:  # Evening peak
            return 1.3
        elif 23 <= hour or hour < 5:  # Deep night
            return 0.7
        else:                   # Early morning
            return 0.8

    def _type_weight(self, request_type: str) -> float:
        weights = {
            "home": 0.8,
            "listing": 1.0,
            "detail": 2.0,
            "search": 1.5,
            "other": 1.2,
        }
        return weights.get(request_type, 1.0)


# ── Dual Rate Limiter ──────────────────────────

class DualRateLimiter:
    """Two-layer rate limiting: global (IP) + per-profile.

    Global layer:
    - Hourly and daily hard caps
    - Block-based cooldown
    - Fatigue-driven slowdown

    Per-profile layer:
    - Individual request counters
    - Profile health-based throttling
    - Profile-specific cooldowns
    """

    def __init__(self, settings: Any = None) -> None:
        if settings is None:
            from src.settings import RateLimitSettings
            settings = RateLimitSettings()
        self._s = settings

        # Global state
        self._hour_window: deque[float] = deque()
        self._day_window: deque[float] = deque()
        self._block_window: deque[float] = deque()
        self._cooldown_until: float = 0.0
        self._consecutive_blocks: int = 0

        # Per-profile state
        self._profile_state: dict[str, dict[str, Any]] = {}

    async def acquire(
        self,
        profile_id: str = "default",
        url: str = "",
    ) -> bool:
        """Request permission to send a request.

        Returns True if request can proceed, False if blocked.
        """
        now = tmod.time()

        # Prune windows
        self._prune(now)

        # ── Global checks ──
        if self._hour_window and len(self._hour_window) >= self._s.requests_per_hour:
            logger.warning("Global hourly cap reached")
            return False
        if self._day_window and len(self._day_window) >= self._s.requests_per_day:
            logger.warning("Global daily cap reached")
            return False
        if now < self._cooldown_until:
            return False

        # ── Per-profile checks ──
        ps = self._profile_state.setdefault(profile_id, {
            "requests": 0,
            "blocks": 0,
            "cooldown_until": 0.0,
            "last_request": 0.0,
        })

        if now < ps["cooldown_until"]:
            return False

        # Profile max (60% of global per-hour)
        profile_requests = ps.get("requests", 0)

        # Record
        self._hour_window.append(now)
        self._day_window.append(now)
        ps["requests"] = profile_requests + 1
        ps["last_request"] = now

        return True

    def report_block(self, profile_id: str = "default") -> None:
        """Report a blocked request."""
        now = tmod.time()
        self._block_window.append(now)
        self._consecutive_blocks += 1

        ps = self._profile_state.get(profile_id, {})
        ps["blocks"] = ps.get("blocks", 0) + 1

        if self._consecutive_blocks >= self._s.cooldown_after_blocks:
            self._cooldown_until = now + self._s.cooldown_minutes * 60
            logger.warning(
                "Global cooldown for %.0f min after %d consecutive blocks",
                self._s.cooldown_minutes,
                self._consecutive_blocks,
            )

        if ps.get("blocks", 0) >= 3:
            ps["cooldown_until"] = now + self._s.cooldown_minutes * 60 * 2
            logger.warning(
                "Profile %s cooldown for %.0f min",
                profile_id,
                self._s.cooldown_minutes * 2,
            )

    def report_success(self, profile_id: str = "default") -> None:
        """Report a successful request."""
        self._consecutive_blocks = max(0, self._consecutive_blocks - 1)

    def _prune(self, now: float) -> None:
        while self._hour_window and self._hour_window[0] < now - 3600:
            self._hour_window.popleft()
        while self._day_window and self._day_window[0] < now - 86400:
            self._day_window.popleft()
        while self._block_window and self._block_window[0] < now - 3600:
            self._block_window.popleft()

    def get_stats(self) -> dict[str, Any]:
        return {
            "hour_count": len(self._hour_window),
            "day_count": len(self._day_window),
            "hourly_cap": self._s.requests_per_hour,
            "daily_cap": self._s.requests_per_day,
            "blocks_recent": len(self._block_window),
            "consecutive_blocks": self._consecutive_blocks,
            "cooldown": self._cooldown_until > tmod.time(),
            "profiles": len(self._profile_state),
        }


# ── Survival Brain (orchestrator) ──────────────

class SurvivalBrain:
    """Central intelligence for survival strategy.

    Orchestrates all survival subsystems:
    - PredictiveDelay: when to send next request
    - DualRateLimiter: whether we're allowed to send
    - ContentChangeDetector: whether we need to send at all
    - PriorityQueue: which request to send first
    """

    def __init__(self, settings: Any = None) -> None:
        if settings is None:
            from src.settings import HLTVSettings
            settings = HLTVSettings()
        self._s = settings
        self._delay_calc = PredictiveDelay(settings.rate_limit)
        self._limiter = DualRateLimiter(settings.rate_limit)
        self._detector = ContentChangeDetector()
        self._queue: list[PriorityRequest] = []
        self._stats: dict[str, Any] = {
            "total_requests": 0,
            "skipped_unchanged": 0,
            "delayed": 0,
        }

    @property
    def delay_calc(self) -> PredictiveDelay:
        return self._delay_calc

    @property
    def limiter(self) -> DualRateLimiter:
        return self._limiter

    @property
    def detector(self) -> ContentChangeDetector:
        return self._detector

    def enqueue(self, req: PriorityRequest) -> None:
        """Add a request to the priority queue."""
        heapq.heappush(self._queue, req)

    def dequeue(self) -> PriorityRequest | None:
        """Get the highest-priority request."""
        if self._queue:
            return heapq.heappop(self._queue)
        return None

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    async def should_request(
        self,
        url: str,
        *,
        profile_id: str = "default",
        request_type: str = "listing",
        profile_health: float = 1.0,
        fatigue_score: float = 0.0,
    ) -> tuple[bool, float]:
        """Decide whether to proceed with a request and compute optimal delay.

        Returns (can_proceed, wait_seconds).
        """
        # 1. Rate limit check
        allowed = await self._limiter.acquire(profile_id, url)
        if not allowed:
            return False, 60.0

        # 2. Compute optimal delay
        delay = self._delay_calc.compute(
            fatigue_score=fatigue_score,
            request_type=request_type,
            profile_health=profile_health,
        )

        self._stats["total_requests"] += 1
        return True, delay

    def check_content_changed(self, url: str, content: str) -> bool:
        """Check if content has changed since last fetch."""
        changed = self._detector.has_changed(url, content)
        if not changed:
            self._stats["skipped_unchanged"] += 1
        return changed

    def get_stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "queue_size": self.queue_size,
            "limiter": self._limiter.get_stats(),
        }


__all__ = [
    "SurvivalBrain",
    "PriorityRequest",
    "PredictiveDelay",
    "DualRateLimiter",
    "ContentChangeDetector",
]
