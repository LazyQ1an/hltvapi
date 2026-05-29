"""
Multi-profile cross-cover coordination — simulate a multi-device household
behind a single IP to dilute scraping signal. v9.0

A single IP exposing one fingerprint profile doing heavy data extraction
quickly burns its trust. But Cloudflare treats an IP with 3-5 distinct
device fingerprints doing mixed activities (some heavy, some casual,
some mobile) as a small household/office NAT — which is normal internet
behaviour.

Strategy:
- Assign profiles distinct "personas" (power user, casual browser, mobile)
- Rotate between personas with weighted selection
- Casual personas do high-trust, low-value browsing
- Power-user persona does actual data extraction, but diluted
- After heavy scraping, switch to casual persona to "wash" the IP score
- Monitor CF response signals and trigger reactive persona switches

Components:
- ProfilePersona: device + behaviour archetype
- CrossCoverStrategy: selection + rotation logic
- ReactiveBackoff: monitor CF challenge signals, force mode switches
"""

from __future__ import annotations

import logging
import random
import time as tmod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

logger = logging.getLogger("hltv.core.cross_cover")


# ---------------------------------------------------------------------------
# Persona types
# ---------------------------------------------------------------------------

class PersonaType(Enum):
    """Distinct user archetypes for multi-profile rotation."""
    POWER_USER = auto()      # Does actual data extraction, medium weight
    CASUAL_BROWSER = auto()  # Reads news, checks scores, low weight
    MOBILE_USER = auto()     # Mobile UA, light browsing
    ESPORTS_FAN = auto()     # Heavy on match pages, but sporadic
    STATS_NERD = auto()      # Deep stats pages, low frequency
    AFK_IDLER = auto()       # Just sits on homepage, does nothing


@dataclass
class ProfilePersona:
    """A profile assigned a specific behavioural archetype."""
    profile_id: str
    persona: PersonaType
    weight: float                          # selection weight (higher = used more)
    device_type: str = "desktop"           # desktop, mobile, tablet
    os_platform: str = "windows"           # windows, macos, linux
    browser_family: str = "chrome"         # chrome, firefox, safari
    request_types: list[str] = field(default_factory=lambda: ["listing"])
    max_requests_per_session: int = 5
    cooldown_after_session: float = 30.0   # seconds
    # Runtime state
    _last_used: float = 0.0
    _session_count: int = 0
    _total_requests: int = 0
    _block_count: int = 0

    @property
    def is_available(self) -> bool:
        return tmod.time() - self._last_used >= self.cooldown_after_session

    @property
    def health_score(self) -> float:
        total = max(1, self._total_requests)
        return 1.0 - (self._block_count / total)


# ---------------------------------------------------------------------------
# Predefined persona catalog
# ---------------------------------------------------------------------------

def _build_default_personas() -> list[ProfilePersona]:
    """Build standard persona roster for HLTV household simulation."""
    return [
        ProfilePersona(
            profile_id="power_user_1",
            persona=PersonaType.POWER_USER,
            weight=0.25,
            device_type="desktop",
            os_platform="windows",
            browser_family="chrome",
            request_types=["detail", "stats", "listing"],
            max_requests_per_session=5,
            cooldown_after_session=45.0,
        ),
        ProfilePersona(
            profile_id="casual_1",
            persona=PersonaType.CASUAL_BROWSER,
            weight=0.30,
            device_type="desktop",
            os_platform="windows",
            browser_family="chrome",
            request_types=["listing", "detail"],
            max_requests_per_session=3,
            cooldown_after_session=20.0,
        ),
        ProfilePersona(
            profile_id="mobile_1",
            persona=PersonaType.MOBILE_USER,
            weight=0.15,
            device_type="mobile",
            os_platform="android",
            browser_family="chrome",
            request_types=["listing"],
            max_requests_per_session=2,
            cooldown_after_session=15.0,
        ),
        ProfilePersona(
            profile_id="fan_1",
            persona=PersonaType.ESPORTS_FAN,
            weight=0.15,
            device_type="desktop",
            os_platform="macos",
            browser_family="safari",
            request_types=["detail", "listing"],
            max_requests_per_session=3,
            cooldown_after_session=60.0,
        ),
        ProfilePersona(
            profile_id="nerd_1",
            persona=PersonaType.STATS_NERD,
            weight=0.10,
            device_type="desktop",
            os_platform="windows",
            browser_family="firefox",
            request_types=["stats", "detail"],
            max_requests_per_session=4,
            cooldown_after_session=90.0,
        ),
        ProfilePersona(
            profile_id="idler_1",
            persona=PersonaType.AFK_IDLER,
            weight=0.05,
            device_type="desktop",
            os_platform="windows",
            browser_family="chrome",
            request_types=[],
            max_requests_per_session=1,
            cooldown_after_session=120.0,
        ),
    ]


# ---------------------------------------------------------------------------
# Cross-cover strategy
# ---------------------------------------------------------------------------

class CrossCoverStrategy:
    """Manage persona rotation to dilute single-profile scraping signal.

    Core algorithm:
    1. Select persona by weighted random (recently used deprioritized)
    2. Execute session (N requests of their preferred type)
    3. Record outcome (blocks, response times)
    4. Adjust weights based on CF challenge signals
    5. After heavy extraction, force casual persona for cooldown

    Usage:
        strategy = CrossCoverStrategy()
        persona = strategy.select_next()
        # ... use persona's profile for a session ...
        strategy.record_outcome(persona, blocks=0, response_time=1.2)
    """

    def __init__(self, personas: list[ProfilePersona] | None = None) -> None:
        self._personas = personas or _build_default_personas()
        self._recent: list[str] = []     # recently used persona IDs
        self._max_recent = 3
        self._force_casual_until: float = 0.0  # timestamp when forced casual ends
        self._block_streak: int = 0
        self._total_sessions: int = 0

    @property
    def personas(self) -> list[ProfilePersona]:
        return self._personas

    def select_next(self, prefer_casual: bool = False) -> ProfilePersona:
        """Select the next persona to use.

        Args:
            prefer_casual: Force selection of a low-intensity persona
                           (used after block detection to wash IP score).
        """
        now = tmod.time()

        # If forced casual mode is active
        if now < self._force_casual_until or prefer_casual:
            casual = [p for p in self._personas
                      if p.persona in (PersonaType.CASUAL_BROWSER, PersonaType.MOBILE_USER, PersonaType.AFK_IDLER)
                      and p.profile_id not in self._recent[-2:]]
            if casual:
                persona = random.choice(casual)
                self._use_persona(persona)
                return persona

        # Normal weighted selection, deprioritize recently used
        available = [p for p in self._personas if p.is_available]
        if not available:
            # All on cooldown — pick least recently used
            available = sorted(self._personas, key=lambda p: p._last_used)[:3]

        # Weight by persona weight, reduced for recently used
        weights: list[float] = []
        for p in available:
            w = p.weight
            if p.profile_id in self._recent:
                w *= 0.3  # heavily deprioritize recently used
            weights.append(max(0.01, w))

        persona = random.choices(available, weights=weights, k=1)[0]
        self._use_persona(persona)
        return persona

    def _use_persona(self, persona: ProfilePersona) -> None:
        persona._last_used = tmod.time()
        persona._session_count += 1
        self._recent.append(persona.profile_id)
        if len(self._recent) > self._max_recent:
            self._recent.pop(0)
        self._total_sessions += 1

    def record_outcome(
        self,
        persona: ProfilePersona,
        blocks: int = 0,
        response_time: float = 0.0,
        http_status: int = 200,
    ) -> None:
        """Record the outcome of a persona's session."""
        persona._total_requests += 1
        persona._block_count += blocks

        if blocks > 0:
            self._block_streak += blocks
            # Force casual browsing to wash the IP score
            if self._block_streak >= 2:
                cooldown = min(5.0 + self._block_streak * 2.0, 30.0)
                self._force_casual_until = tmod.time() + cooldown * 60
                logger.warning(
                    "Block streak %d — forcing casual mode for %.0f min",
                    self._block_streak, cooldown,
                )
        else:
            self._block_streak = max(0, self._block_streak - 1)

        # Adjust persona weight based on outcome
        if blocks > 0:
            persona.weight = max(0.02, persona.weight * 0.85)
        elif persona._session_count > 10 and persona._block_count == 0:
            persona.weight = min(0.50, persona.weight * 1.02)

    def get_active_persona_summary(self) -> dict[str, Any]:
        """Return summary of all personas for monitoring."""
        return {
            "total_sessions": self._total_sessions,
            "block_streak": self._block_streak,
            "forced_casual": tmod.time() < self._force_casual_until,
            "personas": [
                {
                    "id": p.profile_id,
                    "type": p.persona.name,
                    "weight": round(p.weight, 3),
                    "sessions": p._session_count,
                    "requests": p._total_requests,
                    "blocks": p._block_count,
                    "health": round(p.health_score, 3),
                    "available": p.is_available,
                    "device": f"{p.os_platform}/{p.device_type}/{p.browser_family}",
                }
                for p in self._personas
            ],
        }

    def force_casual_cooldown(self, minutes: float = 10.0) -> None:
        """Manually trigger a casual-only browsing period."""
        self._force_casual_until = tmod.time() + minutes * 60
        logger.info("Forced casual cooldown for %.0f min", minutes)


# ---------------------------------------------------------------------------
# Reactive backoff: CF challenge type response
# ---------------------------------------------------------------------------

class ChallengeResponseBrain:
    """Monitor CF challenge signals and trigger reactive countermeasures.

    Different challenge types demand different responses:
    - 403 with Turnstile JS: Stop all scraping, go full casual for 15+ min
    - 429 (rate limit): Halve request rate, extend delays
    - 503 (overload): Switch to minimal mode, only critical requests
    - Slow responses >5s: Possible silent challenge, ease off
    - JavaScript challenge page (IUAM): Full stop, long cooldown
    """

    CHALLENGE_403 = "hard_block"
    CHALLENGE_429 = "rate_limit"
    CHALLENGE_503 = "server_defense"
    CHALLENGE_SLOW = "silent_challenge"
    CHALLENGE_IUAM = "iuam_challenge"

    def __init__(self) -> None:
        self._challenge_history: list[tuple[str, float, str]] = []  # (type, timestamp, detail)
        self._current_level: int = 0  # 0=normal, 1=elevated, 2=defensive, 3=emergency
        self._level_changed_at: float = tmod.time()

    def process_response(
        self,
        status_code: int,
        response_time: float,
        html: str = "",
    ) -> str | None:
        """Process a response and return recommended action or None.

        Returns:
            None if no action needed, or action string:
            'reduce_rate', 'switch_casual', 'long_cooldown', 'emergency_stop'
        """
        now = tmod.time()
        challenge_type: str | None = None

        if status_code == 403:
            if "turnstile" in html.lower() or "challenge-platform" in html.lower():
                challenge_type = self.CHALLENGE_403
            elif "iuam" in html.lower() or "attention required" in html.lower():
                challenge_type = self.CHALLENGE_IUAM
        elif status_code == 429:
            challenge_type = self.CHALLENGE_429
        elif status_code == 503:
            challenge_type = self.CHALLENGE_503
        elif response_time > 8.0:
            challenge_type = self.CHALLENGE_SLOW

        if challenge_type:
            self._challenge_history.append((challenge_type, now, str(status_code)))
            # Trim history
            if len(self._challenge_history) > 50:
                self._challenge_history = self._challenge_history[-30:]

        # Determine current threat level
        recent_challenges = [c for c in self._challenge_history if now - c[1] < 600]
        hard_blocks = sum(1 for c in recent_challenges if c[0] in (self.CHALLENGE_403, self.CHALLENGE_IUAM))
        soft_blocks = sum(1 for c in recent_challenges if c[0] in (self.CHALLENGE_429, self.CHALLENGE_503, self.CHALLENGE_SLOW))

        old_level = self._current_level
        if hard_blocks >= 2:
            self._current_level = 3  # emergency
        elif hard_blocks >= 1 or soft_blocks >= 3:
            self._current_level = 2  # defensive
        elif soft_blocks >= 1:
            self._current_level = 1  # elevated
        elif now - self._level_changed_at > 600 and self._current_level > 0:
            self._current_level = max(0, self._current_level - 1)  # gradual recovery

        if self._current_level != old_level:
            self._level_changed_at = now
            logger.info("Challenge level: %d → %d", old_level, self._current_level)

        # Map level to action
        if self._current_level == 3:
            return "emergency_stop"
        elif self._current_level == 2:
            return "long_cooldown"
        elif self._current_level == 1:
            return "switch_casual"

        return None

    @property
    def current_level(self) -> int:
        return self._current_level

    @property
    def is_emergency(self) -> bool:
        return self._current_level >= 3

    def get_stats(self) -> dict[str, Any]:
        now = tmod.time()
        recent = [c for c in self._challenge_history if now - c[1] < 3600]
        return {
            "level": self._current_level,
            "level_name": {0: "normal", 1: "elevated", 2: "defensive", 3: "emergency"}.get(self._current_level, "unknown"),
            "challenges_1h": len(recent),
            "challenges_total": len(self._challenge_history),
            "last_challenge": self._challenge_history[-1] if self._challenge_history else None,
        }


__all__ = [
    "PersonaType",
    "ProfilePersona",
    "CrossCoverStrategy",
    "ChallengeResponseBrain",
]
