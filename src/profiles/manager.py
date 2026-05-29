"""Browser profile management for single-IP multi-identity operation. v6.1

Enhanced with:
- Smart health scoring: weighted by challenge frequency, response time,
  cookie validity, and profile age
- Auto-evolution: profiles micro-adjust fingerprints over time
- Dynamic selection: health-weighted probabilistic choice (not simple rotation)
- Profile retirement: profiles exceeding max lifetime are replaced
- Evolution history: track fingerprint changes for debugging
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time as tmod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.settings import ProfileSettings

logger = logging.getLogger("hltv.profiles")


@dataclass
class Profile:
    """A single browser identity with persistent disk storage."""

    name: str
    user_data_dir: Path
    created_at: float = field(default_factory=tmod.time)
    last_used: float = field(default_factory=tmod.time)
    request_count: int = 0
    success_count: int = 0
    block_count: int = 0
    _cookies: dict[str, str] = field(default_factory=dict, repr=False)

    # Enhanced metrics
    _response_times: list[float] = field(default_factory=list, repr=False)
    _challenge_times: list[float] = field(default_factory=list, repr=False)
    _evolution_count: int = 0
    _last_evolution: float = 0.0
    _fingerprint_seed: int = 0

    def __post_init__(self) -> None:
        if self._fingerprint_seed == 0:
            self._fingerprint_seed = int(
                hashlib.sha256(self.name.encode()).hexdigest()[:8], 16
            )

    # ── Smart health scoring ────────────────────

    @property
    def health_score(self) -> float:
        """Weighted health score 0.0 (dead) to 1.0 (perfect).

        Components:
        - Success rate (40%): ratio of successful to total requests
        - Block recency (25%): recent blocks penalize more
        - Response time trend (15%): slowing = unhealthy
        - Cookie freshness (10%): older cookies = lower score
        - Profile age (10%): very old profiles get slight decay
        """
        now = tmod.time()
        total = self.success_count + self.block_count

        # Success rate
        if total == 0:
            sr = 1.0
        else:
            sr = self.success_count / total

        # Block recency (blocks in last 1800s penalize more)
        recent_blocks = sum(1 for t in self._challenge_times if now - t < 1800)
        br = max(0.0, 1.0 - recent_blocks * 0.25)

        # Response time trend
        rt = self._response_time_trend()

        # Cookie freshness
        cf = self._cookie_freshness(now)

        # Profile age (slight decay after 48h, accelerates after 72h)
        age_hours = (now - self.created_at) / 3600
        if age_hours < 48:
            ag = 1.0
        elif age_hours < 72:
            ag = 1.0 - (age_hours - 48) / 24 * 0.1
        else:
            ag = 0.9 - min(0.4, (age_hours - 72) / 168 * 0.4)

        return round(
            0.40 * sr + 0.25 * br + 0.15 * rt + 0.10 * cf + 0.10 * ag,
            4,
        )

    def _response_time_trend(self) -> float:
        """Check if response times are stable (1.0) or degrading (0.0)."""
        if len(self._response_times) < 3:
            return 1.0
        recent = self._response_times[-5:]
        if len(recent) < 2:
            return 1.0
        # Check if trend is upward
        first_half = sum(recent[:len(recent)//2]) / max(len(recent)//2, 1)
        second_half = sum(recent[len(recent)//2:]) / max(len(recent) - len(recent)//2, 1)
        if first_half <= 0:
            return 0.5
        ratio = second_half / first_half
        if ratio < 1.1:
            return 1.0
        if ratio < 2.0:
            return 1.0 - (ratio - 1.1) / 0.9 * 0.5
        return max(0.1, 0.5 - (ratio - 2.0) * 0.1)

    def _cookie_freshness(self, now: float) -> float:
        """Score based on cookie age (1.0 = fresh, 0.0 = stale/absent)."""
        if "cf_clearance" not in self._cookies:
            return 0.3
        # We don't track birth time directly, estimate from last_used
        age = now - self.last_used
        if age < 600:
            return 1.0
        if age < 1800:
            return 1.0 - (age - 600) / 1200 * 0.4
        if age < 3600:
            return 0.6 - (age - 1800) / 1800 * 0.4
        return 0.2

    # ── Auto-evolution ──────────────────────────

    def evolve(self, degree: float = 0.02) -> dict[str, Any]:
        """Micro-adjust fingerprint to simulate natural browser drift.

        Over time, real browser fingerprints change slightly (GPU driver
        updates, font installations, etc.). We simulate this by slightly
        modifying the fingerprint seed.

        Returns dict with evolution details for logging.
        """
        self._evolution_count += 1
        self._last_evolution = tmod.time()

        # Slightly perturb the seed
        old_seed = self._fingerprint_seed
        delta = random.randint(-int(degree * 1e7), int(degree * 1e7))
        self._fingerprint_seed = max(1, self._fingerprint_seed + delta)

        logger.debug(
            "Profile %s evolved: seed %d -> %d (evolution #%d)",
            self.name, old_seed, self._fingerprint_seed, self._evolution_count,
        )

        return {
            "profile": self.name,
            "old_seed": old_seed,
            "new_seed": self._fingerprint_seed,
            "evolution_count": self._evolution_count,
        }

    @property
    def fingerprint_seed(self) -> int:
        return self._fingerprint_seed

    # ── Cookie persistence ──────────────────────

    @property
    def cookie_file(self) -> Path:
        return self.user_data_dir / "cookies.json"

    def save_cookies(self, cookies: dict[str, str]) -> None:
        self._cookies.update(cookies)
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": self.name,
            "saved_at": tmod.time(),
            "cookies": self._cookies,
        }
        self.cookie_file.write_text(json.dumps(payload, indent=2))

    def load_cookies(self) -> dict[str, str]:
        if self.cookie_file.exists():
            try:
                data = json.loads(self.cookie_file.read_text())
                cookies = data.get("cookies", {})
                self._cookies.update(cookies)
                return cookies
            except Exception:
                pass
        return {}

    # ── Recording ───────────────────────────────

    def record_success(self, response_time: float = 0.0) -> None:
        self.last_used = tmod.time()
        self.request_count += 1
        self.success_count += 1
        if response_time > 0:
            self._response_times.append(response_time)
            if len(self._response_times) > 50:
                self._response_times.pop(0)

    def record_block(self) -> None:
        self.last_used = tmod.time()
        self.request_count += 1
        self.block_count += 1
        self._challenge_times.append(tmod.time())
        if len(self._challenge_times) > 20:
            self._challenge_times.pop(0)

    @property
    def age_hours(self) -> float:
        return (tmod.time() - self.created_at) / 3600


class ProfileManager:
    """Smart profile lifecycle manager.

    Enhanced with:
    - Health-weighted dynamic selection (not simple round-robin)
    - Auto-evolution scheduling
    - Profile retirement and replacement
    - Detailed health reporting
    """

    def __init__(self, settings: ProfileSettings | None = None) -> None:
        self._settings = settings or ProfileSettings()
        self._profiles: list[Profile] = []
        self._index: int = 0

    @property
    def profiles(self) -> list[Profile]:
        return list(self._profiles)

    @property
    def current(self) -> Profile | None:
        if not self._profiles:
            return None
        return self._profiles[self._index]

    async def initialize(self) -> None:
        base = self._settings.path
        base.mkdir(parents=True, exist_ok=True)
        self._profiles = []
        for i in range(self._settings.count):
            name = f"profile_{i + 1}"
            user_dir = base / name
            profile = Profile(name=name, user_data_dir=user_dir)
            profile.load_cookies()
            self._profiles.append(profile)
        logger.info(
            "ProfileManager v6.1: %d profiles in %s",
            len(self._profiles), str(base),
        )

    # ── Smart selection ─────────────────────────

    async def select(self) -> Profile:
        """Select the best profile using health-weighted probability.

        Healthier profiles are more likely to be chosen, but some
        randomness ensures all profiles get occasional use (prevents
        stale cookies).
        """
        if not self._profiles:
            raise RuntimeError("ProfileManager not initialized")

        # Get health scores
        scores = [p.health_score for p in self._profiles]
        min_score = min(scores) if scores else 0.0

        # Shift scores so the lowest is at least 0.1 (everyone gets a chance)
        shifted = [max(0.1, s - min_score + 0.1) for s in scores]
        total = sum(shifted)

        if total <= 0:
            # All dead, pick randomly
            self._index = random.randint(0, len(self._profiles) - 1)
        else:
            # Weighted random selection
            r = random.random() * total
            cumulative = 0.0
            for i, w in enumerate(shifted):
                cumulative += w
                if r <= cumulative:
                    self._index = i
                    break

        profile = self._profiles[self._index]

        # Check if evolution is due
        if self._should_evolve(profile):
            profile.evolve(self._settings.evolution_degree)

        logger.debug(
            "Selected %s (health=%.3f, age=%.1fh)",
            profile.name, profile.health_score, profile.age_hours,
        )
        return profile

    async def rotate(self) -> Profile:
        """Rotate to next healthy profile (backward-compat wrapper)."""
        return await self.select()

    def _should_evolve(self, profile: Profile) -> bool:
        """Check if this profile should micro-evolve its fingerprint."""
        elapsed = tmod.time() - profile._last_evolution
        return elapsed > self._settings.evolution_interval

    def should_rotate(self) -> bool:
        """Check if the current profile should be switched."""
        if not self.current:
            return True
        p = self.current
        if p.request_count >= self._settings.max_requests_per_profile:
            return True
        if p.age_hours > self._settings.max_lifetime_hours:
            return True
        if p.health_score < self._settings.health_threshold_low and p.request_count > 5:
            return True
        return False

    # ── Recording ───────────────────────────────

    def record_success(self, response_time: float = 0.0) -> None:
        if self.current:
            self.current.record_success(response_time)

    def record_block(self) -> None:
        if self.current:
            self.current.record_block()

    async def save_all_cookies(self, cookies: dict[str, str]) -> None:
        for profile in self._profiles:
            profile.save_cookies(cookies)

    def best_profile(self) -> Profile | None:
        if not self._profiles:
            return None
        return max(self._profiles, key=lambda p: p.health_score)

    # ── Retirement ──────────────────────────────

    async def retire_oldest(self) -> Profile | None:
        """Retire the oldest profile and create a replacement."""
        if not self._profiles:
            return None

        oldest = min(self._profiles, key=lambda p: p.created_at)
        if oldest.age_hours < self._settings.max_lifetime_hours:
            return None

        # Create replacement
        base = self._settings.path
        new_name = f"profile_{int(tmod.time()) % 100000}"
        new_dir = base / new_name
        new_profile = Profile(name=new_name, user_data_dir=new_dir)

        # Replace in list
        for i, p in enumerate(self._profiles):
            if p.name == oldest.name:
                self._profiles[i] = new_profile
                if self._index == i:
                    self._index = (i + 1) % len(self._profiles)
                break

        logger.info(
            "Retired %s (age=%.1fh), created %s",
            oldest.name, oldest.age_hours, new_name,
        )
        return new_profile

    def get_health_report(self) -> dict[str, Any]:
        """Detailed health report for all profiles."""
        return {
            "profiles": [
                {
                    "name": p.name,
                    "health": p.health_score,
                    "age_hours": round(p.age_hours, 1),
                    "requests": p.request_count,
                    "success": p.success_count,
                    "blocks": p.block_count,
                    "evolutions": p._evolution_count,
                    "has_cookies": bool(p._cookies),
                }
                for p in self._profiles
            ],
            "current": self.current.name if self.current else None,
        }


__all__ = ["Profile", "ProfileManager"]
