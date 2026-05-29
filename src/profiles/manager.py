"""
Browser profile management for single-IP multi-identity operation. v7.0

v7.0: Sleep-wake cycles + growth/aging
- Profiles auto-sleep after prolonged inactivity
- Sleeping profiles can be reactivated after cooldown
- Profile growth: success rate, request count, cookie age influence
- Profile aging: decay over time, evolution tracking
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
    name: str
    user_data_dir: Path
    created_at: float = field(default_factory=tmod.time)
    last_used: float = field(default_factory=tmod.time)
    request_count: int = 0
    success_count: int = 0
    block_count: int = 0
    _cookies: dict[str, str] = field(default_factory=dict, repr=False)
    _response_times: list[float] = field(default_factory=list, repr=False)
    _challenge_times: list[float] = field(default_factory=list, repr=False)
    _evolution_count: int = 0
    _last_evolution: float = 0.0
    _fingerprint_seed: int = 0
    # v7.0
    _asleep: bool = False
    _sleep_since: float = 0.0
    _wake_count: int = 0
    _growth_stage: int = 0  # 0=new, 1=established, 2=veteran

    def __post_init__(self) -> None:
        if self._fingerprint_seed == 0:
            self._fingerprint_seed = int(
                hashlib.sha256(self.name.encode()).hexdigest()[:8], 16
            )

    @property
    def health_score(self) -> float:
        now = tmod.time()
        total = self.success_count + self.block_count
        sr = self.success_count / total if total > 0 else 1.0
        recent_blocks = sum(1 for t in self._challenge_times if now - t < 1800)
        br = max(0.0, 1.0 - recent_blocks * 0.25)
        rt = self._response_time_trend()
        cf = self._cookie_freshness(now)
        age_hours = (now - self.created_at) / 3600
        if age_hours < 48:
            ag = 1.0
        elif age_hours < 72:
            ag = 1.0 - (age_hours - 48) / 24 * 0.1
        else:
            ag = 0.9 - min(0.4, (age_hours - 72) / 168 * 0.4)
        # Growth bonus
        growth = 1.0 + self._growth_stage * 0.05
        return round(min(1.0, (0.40*sr + 0.25*br + 0.15*rt + 0.10*cf + 0.10*ag) * growth), 4)

    def _response_time_trend(self) -> float:
        if len(self._response_times) < 3:
            return 1.0
        recent = self._response_times[-5:]
        if len(recent) < 2:
            return 1.0
        fh = sum(recent[:len(recent)//2]) / max(len(recent)//2, 1)
        sh = sum(recent[len(recent)//2:]) / max(len(recent) - len(recent)//2, 1)
        if fh <= 0:
            return 0.5
        ratio = sh / fh
        if ratio < 1.1:
            return 1.0
        if ratio < 2.0:
            return 1.0 - (ratio - 1.1) / 0.9 * 0.5
        return max(0.1, 0.5 - (ratio - 2.0) * 0.1)

    def _cookie_freshness(self, now: float) -> float:
        if "cf_clearance" not in self._cookies:
            return 0.3
        age = now - self.last_used
        if age < 600:
            return 1.0
        if age < 1800:
            return 1.0 - (age - 600) / 1200 * 0.4
        if age < 3600:
            return 0.6 - (age - 1800) / 1800 * 0.4
        return 0.2

    @property
    def is_asleep(self) -> bool:
        return self._asleep

    def sleep(self) -> None:
        self._asleep = True
        self._sleep_since = tmod.time()
        logger.debug("Profile %s sleeping", self.name)

    def wake(self) -> None:
        self._asleep = False
        self._sleep_since = 0.0
        self._wake_count += 1
        # Growth advancement on wake
        if self._wake_count >= 3 and self._growth_stage < 2:
            self._growth_stage += 1
            logger.debug("Profile %s advanced to growth stage %d", self.name, self._growth_stage)
        logger.debug("Profile %s woken (wake #%d)", self.name, self._wake_count)

    def evolve(self, degree: float = 0.02) -> dict[str, Any]:
        self._evolution_count += 1
        self._last_evolution = tmod.time()
        old_seed = self._fingerprint_seed
        delta = random.randint(-int(degree * 1e7), int(degree * 1e7))
        self._fingerprint_seed = max(1, self._fingerprint_seed + delta)
        # Growth check
        if self.request_count > 100 and self._growth_stage < 1:
            self._growth_stage = 1
        if self.request_count > 500 and self._growth_stage < 2:
            self._growth_stage = 2
        return {"profile": self.name, "old_seed": old_seed, "new_seed": self._fingerprint_seed, "evolutions": self._evolution_count}

    @property
    def fingerprint_seed(self) -> int:
        return self._fingerprint_seed

    @property
    def cookie_file(self) -> Path:
        return self.user_data_dir / "cookies.json"

    def save_cookies(self, cookies: dict[str, str]) -> None:
        self._cookies.update(cookies)
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        payload = {"name": self.name, "saved_at": tmod.time(), "cookies": self._cookies}
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
    """Smart profile lifecycle manager v7.0 with sleep-wake."""

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
        logger.info("ProfileManager v7.0: %d profiles in %s", len(self._profiles), str(base))

    async def select(self) -> Profile:
        if not self._profiles:
            raise RuntimeError("ProfileManager not initialized")
        self._check_sleep_cycles()
        awake = [p for p in self._profiles if not p.is_asleep]
        if not awake:
            logger.warning("All profiles asleep, waking best candidate")
            best = max(self._profiles, key=lambda p: p.health_score)
            best.wake()
            awake = [best]
        scores = [p.health_score for p in awake]
        shifted = [max(0.1, s - min(scores) + 0.1) for s in scores]
        total = sum(shifted)
        r = random.random() * total if total > 0 else 0
        cumulative = 0.0
        for i, w in enumerate(shifted):
            cumulative += w
            if r <= cumulative:
                self._index = self._profiles.index(awake[i])
                break
        profile = self._profiles[self._index]
        if self._should_evolve(profile):
            profile.evolve(self._settings.evolution_degree)
        logger.debug("Selected %s (health=%.3f, stage=%d, asleep=%s)", profile.name, profile.health_score, profile._growth_stage, profile.is_asleep)
        return profile

    async def rotate(self) -> Profile:
        return await self.select()

    def _check_sleep_cycles(self) -> None:
        now = tmod.time()
        for p in self._profiles:
            if not p.is_asleep:
                idle_hours = (now - p.last_used) / 3600
                if idle_hours > self._settings.sleep_after_idle_hours:
                    p.sleep()
            else:
                sleep_hours = (now - p._sleep_since) / 3600
                if sleep_hours > self._settings.wake_cooldown_hours and p.health_score >= self._settings.wake_health_threshold:
                    p.wake()

    def _should_evolve(self, profile: Profile) -> bool:
        return (tmod.time() - profile._last_evolution) > self._settings.evolution_interval

    def should_rotate(self) -> bool:
        if not self.current:
            return True
        p = self.current
        if p.is_asleep:
            return True
        if p.request_count >= self._settings.max_requests_per_profile:
            return True
        if p.age_hours > self._settings.max_lifetime_hours:
            return True
        if p.health_score < self._settings.health_threshold_low and p.request_count > 5:
            return True
        return False

    def record_success(self, response_time: float = 0.0) -> None:
        if self.current:
            self.current.record_success(response_time)

    def record_block(self) -> None:
        if self.current:
            self.current.record_block()

    async def save_all_cookies(self, cookies: dict[str, str]) -> None:
        for p in self._profiles:
            p.save_cookies(cookies)

    def best_profile(self) -> Profile | None:
        return max(self._profiles, key=lambda p: p.health_score) if self._profiles else None

    def get_health_report(self) -> dict[str, Any]:
        return {
            "profiles": [{
                "name": p.name, "health": p.health_score,
                "age_hours": round(p.age_hours, 1), "requests": p.request_count,
                "success": p.success_count, "blocks": p.block_count,
                "evolutions": p._evolution_count, "has_cookies": bool(p._cookies),
                "asleep": p.is_asleep, "growth_stage": p._growth_stage,
                "wake_count": p._wake_count,
            } for p in self._profiles],
            "current": self.current.name if self.current else None,
        }


__all__ = ["Profile", "ProfileManager"]
