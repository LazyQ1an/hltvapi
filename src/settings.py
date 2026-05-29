"""
HLTV Scraper Settings — single source of truth. (v6.1)

All configuration lives here as dataclasses with sensible defaults.
Environment variables override with HLTV_ prefix (e.g., HLTV_MODE=light).

Usage:
    from src.settings import load_settings
    settings = load_settings()
    settings = load_settings(mode="light")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


# ── Profile settings ──────────────────────────────────────

@dataclass
class ProfileSettings:
    """Browser profile management."""

    count: int = 3
    """Number of profiles to maintain (3-5 recommended for single IP)."""

    base_dir: str = ""
    """Base directory for profile storage. Defaults to ~/.hltv_profiles/."""

    rotate_interval: int = 300
    """Seconds between automatic profile switches."""

    max_requests_per_profile: int = 500
    """Max requests before forcing a profile rotation."""

    max_lifetime_hours: float = 72.0
    """Maximum profile lifetime before forced retirement (creates a new one)."""

    health_threshold_low: float = 0.3
    """Health score below which a profile is considered unhealthy."""

    health_threshold_good: float = 0.7
    """Health score above which a profile is preferred for selection."""

    evolution_interval: int = 600
    """Seconds between fingerprint micro-evolutions (subtle changes)."""

    evolution_degree: float = 0.02
    """How much to evolve fingerprints (0.0 = none, 0.1 = moderate)."""

    def __post_init__(self) -> None:
        if not self.base_dir:
            self.base_dir = str(Path.home() / ".hltv_profiles")

    @property
    def path(self) -> Path:
        return Path(self.base_dir)


# ── Stealth (Nodriver) settings ────────────────────────────

@dataclass
class StealthSettings:
    """Deep Nodriver browser configuration for Cloudflare bypass."""

    headless: bool = True
    """Run Chrome in headless mode."""

    chrome_path: str | None = None
    """Path to system Chrome binary. Auto-detected if None."""

    window_width: int = 1920
    window_height: int = 1080

    cdp_minimization: bool = True
    """Inject CDP cleanup scripts (deep armor mode)."""

    cdp_deep_armor: bool = True
    """Use comprehensive CDP_FULL_ARMOR (Runtime, Page, Network, Browser, Target, Debugger, Input)."""

    fingerprint_fixation: bool = True
    """Lock fingerprint to profile — same profile = same fingerprint forever."""

    max_pages: int = 5
    """Max concurrent pages before recycling the browser."""

    idle_timeout: int = 300
    """Seconds of inactivity before closing browser."""

    page_timeout: int = 30
    """Timeout in seconds for page navigation."""

    cf_wait_timeout: int = 30
    """Max seconds to wait for Cloudflare challenge resolution."""

    extra_chrome_args: tuple[str, ...] = ()
    """Additional Chrome CLI arguments (appended to defaults)."""


# ── Light (curl_cffi) settings ─────────────────────────────

@dataclass
class LightSettings:
    """curl_cffi light mode configuration."""

    impersonate: str = "chrome131"
    """TLS fingerprint to impersonate."""

    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 2.0

    align_with_profile: bool = True
    """Align User-Agent and headers with active stealth profile for consistency."""

    etag_cache: bool = True
    """Send If-None-Match / If-Modified-Since to reduce unnecessary transfers."""

    etag_cache_size: int = 500
    """Max ETag entries in memory."""


# ── Behavior simulation settings ──────────────────────────

@dataclass
class BehaviorSettings:
    """Human behavior simulation — lightweight, server-friendly."""

    min_delay: float = 2.0
    max_delay: float = 8.0

    scroll_probability: float = 0.3
    scroll_pixels_min: int = 200
    scroll_pixels_max: int = 600

    mouse_move_count: int = 2
    """Number of mouse movements to simulate per page."""

    mouse_curve_points: int = 5
    """Number of intermediate points in mouse movement curves."""

    dwell_listing_min: float = 2.0
    dwell_listing_max: float = 5.0
    dwell_detail_min: float = 6.0
    dwell_detail_max: float = 15.0

    warmup_enabled: bool = True
    warmup_urls: tuple[str, ...] = ("https://www.hltv.org/",)

    browse_trajectory: bool = True
    """Simulate natural browse trajectory (home → listing → detail)."""

    interaction_probability: float = 0.05
    """Probability of performing a light interaction (search, click non-critical)."""


# ── Rate limit settings ───────────────────────────────────

@dataclass
class RateLimitSettings:
    """Rate limiting — single-IP safe defaults."""

    min_delay: float = 2.0
    max_delay: float = 10.0

    requests_per_hour: int = 80
    requests_per_day: int = 1500

    jitter: bool = True

    cooldown_after_blocks: int = 3
    cooldown_minutes: float = 5.0

    adaptive_enabled: bool = True
    """Enable fatigue-based adaptive delay scaling."""

    hibernation_enabled: bool = True
    """Enable automatic hibernation when daily quota exhausted or high fatigue."""

    hibernation_hours_min: float = 8.0
    hibernation_hours_max: float = 14.0
    """Hibernation duration range."""


# ── Main settings ─────────────────────────────────────────

@dataclass
class HLTVSettings:
    """Root configuration.

    All nested settings have sensible defaults tuned for single-IP operation.
    Override via environment: HLTV_MODE=stealth, HLTV_PROFILE_COUNT=5, etc.
    """

    mode: Literal["stealth", "light"] = "stealth"
    base_url: str = "https://www.hltv.org"

    profile: ProfileSettings = field(default_factory=ProfileSettings)
    stealth: StealthSettings = field(default_factory=StealthSettings)
    light: LightSettings = field(default_factory=LightSettings)
    behavior: BehaviorSettings = field(default_factory=BehaviorSettings)
    rate_limit: RateLimitSettings = field(default_factory=RateLimitSettings)

    # Open interfaces
    export_api: bool = True
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    cache_dir: str = ".cache/hltv"
    log_level: str = "INFO"


# ── Loading ───────────────────────────────────────────────

def _apply_env_overrides(settings: HLTVSettings) -> HLTVSettings:
    """Apply HLTV_* environment variable overrides."""
    env = os.environ

    if env.get("HLTV_MODE"):
        v = env["HLTV_MODE"]
        if v in ("stealth", "light"):
            settings.mode = v  # type: ignore[assignment]

    for key, val in [
        ("HLTV_PROFILE_COUNT", "profile.count"),
        ("HLTV_PROFILE_BASE_DIR", "profile.base_dir"),
        ("HLTV_PROFILE_ROTATE_INTERVAL", "profile.rotate_interval"),
        ("HLTV_PROFILE_MAX_LIFETIME", "profile.max_lifetime_hours"),
        ("HLTV_PROFILE_HEALTH_LOW", "profile.health_threshold_low"),
        ("HLTV_PROFILE_HEALTH_GOOD", "profile.health_threshold_good"),
        ("HLTV_STEALTH_HEADLESS", "stealth.headless"),
        ("HLTV_STEALTH_CHROME_PATH", "stealth.chrome_path"),
        ("HLTV_STEALTH_CDP_DEEP", "stealth.cdp_deep_armor"),
        ("HLTV_STEALTH_FINGERPRINT_FIX", "stealth.fingerprint_fixation"),
        ("HLTV_LIGHT_IMPERSONATE", "light.impersonate"),
        ("HLTV_LIGHT_ALIGN", "light.align_with_profile"),
        ("HLTV_BEHAVIOR_MIN_DELAY", "behavior.min_delay"),
        ("HLTV_BEHAVIOR_MAX_DELAY", "behavior.max_delay"),
        ("HLTV_BEHAVIOR_TRAJECTORY", "behavior.browse_trajectory"),
        ("HLTV_RATE_PER_HOUR", "rate_limit.requests_per_hour"),
        ("HLTV_RATE_PER_DAY", "rate_limit.requests_per_day"),
        ("HLTV_RATE_ADAPTIVE", "rate_limit.adaptive_enabled"),
        ("HLTV_RATE_HIBERNATE", "rate_limit.hibernation_enabled"),
        ("HLTV_API_PORT", "api_port"),
        ("HLTV_LOG_LEVEL", "log_level"),
    ]:
        if env.get(key):
            v = env[key]
            obj, attr = val.split(".")
            target = getattr(settings, obj)
            try:
                current = getattr(target, attr)
                if isinstance(current, bool):
                    setattr(target, attr, v.lower() in ("true", "1", "yes"))
                elif isinstance(current, int):
                    setattr(target, attr, int(v))
                elif isinstance(current, float):
                    setattr(target, attr, float(v))
                else:
                    setattr(target, attr, v)
            except (ValueError, TypeError):
                pass

    return settings


def load_settings(
    mode: str | None = None,
    config_path: str | None = None,
) -> HLTVSettings:
    """Load settings with sensible defaults and optional overrides."""
    settings = HLTVSettings()

    if config_path:
        try:
            import yaml
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data:
                _merge_dict(settings, data)
        except ImportError:
            pass
        except Exception:
            pass

    settings = _apply_env_overrides(settings)

    if mode and mode in ("stealth", "light"):
        settings.mode = mode  # type: ignore[assignment]

    return settings


def _merge_dict(settings: HLTVSettings, data: dict[str, Any]) -> None:
    """Merge a flat or nested dict into settings dataclass."""
    for key, value in data.items():
        if hasattr(settings, key):
            target = getattr(settings, key)
            if isinstance(value, dict) and hasattr(target, "__dataclass_fields__"):
                for sub_key, sub_val in value.items():
                    if hasattr(target, sub_key):
                        setattr(target, sub_key, sub_val)
            else:
                setattr(settings, key, value)


__all__ = [
    "HLTVSettings",
    "ProfileSettings",
    "StealthSettings",
    "LightSettings",
    "BehaviorSettings",
    "RateLimitSettings",
    "load_settings",
]
