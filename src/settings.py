"""
HLTV Scraper Settings — single source of truth. v7.0

All configuration lives here as dataclasses with sensible defaults.
Environment variables override with HLTV_ prefix.

v7.0 additions:
- Survival brain: predictive delay, dual-layer rate limits, content detector
- Behavior v2: per-profile behavior personalities
- Fingerprint factory: complete hardware-level fingerprinting
- Profile sleep-wake: dormant profile reactivation
- Light mode JA4 alignment
- Log rotation
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass
class ProfileSettings:
    count: int = 3
    base_dir: str = ""
    rotate_interval: int = 300
    max_requests_per_profile: int = 500
    max_lifetime_hours: float = 72.0
    health_threshold_low: float = 0.3
    health_threshold_good: float = 0.7
    evolution_interval: int = 600
    evolution_degree: float = 0.02
    # v7.0: Sleep-wake
    sleep_after_idle_hours: float = 6.0
    wake_health_threshold: float = 0.5
    wake_cooldown_hours: float = 2.0

    def __post_init__(self) -> None:
        if not self.base_dir:
            self.base_dir = str(Path.home() / ".hltv_profiles")

    @property
    def path(self) -> Path:
        return Path(self.base_dir)


@dataclass
class StealthSettings:
    headless: bool = True
    chrome_path: str | None = None
    window_width: int = 1920
    window_height: int = 1080
    cdp_minimization: bool = True
    cdp_deep_armor: bool = True
    fingerprint_fixation: bool = True
    # v7.0
    use_fingerprint_factory: bool = True
    use_behavior_v2: bool = True
    max_pages: int = 5
    idle_timeout: int = 300
    page_timeout: int = 30
    cf_wait_timeout: int = 30
    extra_chrome_args: tuple[str, ...] = ()
    # v7.0: Memory control
    max_memory_mb: int = 512
    gc_interval: int = 60


@dataclass
class LightSettings:
    impersonate: str = "chrome131"
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 2.0
    align_with_profile: bool = True
    etag_cache: bool = True
    etag_cache_size: int = 500
    # v7.0: JA4 sync
    sync_ja4: bool = True
    sync_header_order: bool = True


@dataclass
class BehaviorSettings:
    min_delay: float = 2.0
    max_delay: float = 8.0
    scroll_probability: float = 0.3
    scroll_pixels_min: int = 200
    scroll_pixels_max: int = 600
    mouse_move_count: int = 2
    mouse_curve_points: int = 5
    dwell_listing_min: float = 2.0
    dwell_listing_max: float = 5.0
    dwell_detail_min: float = 6.0
    dwell_detail_max: float = 15.0
    warmup_enabled: bool = True
    warmup_urls: tuple[str, ...] = ("https://www.hltv.org/",)
    browse_trajectory: bool = True
    interaction_probability: float = 0.05
    # v7.0
    use_v2: bool = True
    per_profile_behavior: bool = True


@dataclass
class RateLimitSettings:
    min_delay: float = 2.0
    max_delay: float = 10.0
    requests_per_hour: int = 80
    requests_per_day: int = 1500
    jitter: bool = True
    cooldown_after_blocks: int = 3
    cooldown_minutes: float = 5.0
    adaptive_enabled: bool = True
    hibernation_enabled: bool = True
    hibernation_hours_min: float = 8.0
    hibernation_hours_max: float = 14.0
    # v7.0
    use_survival_brain: bool = True
    dual_layer_limits: bool = True
    content_change_detection: bool = True


@dataclass
class LoggingSettings:
    level: str = "INFO"
    format: str = "plain"
    file: str = ""
    max_bytes: int = 10_485_760  # 10MB
    backup_count: int = 3


@dataclass
class HLTVSettings:
    mode: Literal["stealth", "light"] = "stealth"
    base_url: str = "https://www.hltv.org"

    profile: ProfileSettings = field(default_factory=ProfileSettings)
    stealth: StealthSettings = field(default_factory=StealthSettings)
    light: LightSettings = field(default_factory=LightSettings)
    behavior: BehaviorSettings = field(default_factory=BehaviorSettings)
    rate_limit: RateLimitSettings = field(default_factory=RateLimitSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)

    export_api: bool = True
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cache_dir: str = ".cache/hltv"


def _apply_env_overrides(settings: HLTVSettings) -> HLTVSettings:
    env = os.environ
    if env.get("HLTV_MODE"):
        v = env["HLTV_MODE"]
        if v in ("stealth", "light"):
            settings.mode = v  # type: ignore[assignment]
    for key, val in [
        ("HLTV_PROFILE_COUNT", "profile.count"),
        ("HLTV_PROFILE_SLEEP", "profile.sleep_after_idle_hours"),
        ("HLTV_STEALTH_HEADLESS", "stealth.headless"),
        ("HLTV_STEALTH_CDP_DEEP", "stealth.cdp_deep_armor"),
        ("HLTV_STEALTH_FACTORY", "stealth.use_fingerprint_factory"),
        ("HLTV_STEALTH_BEHAVIOR_V2", "stealth.use_behavior_v2"),
        ("HLTV_STEALTH_MAX_MEMORY", "stealth.max_memory_mb"),
        ("HLTV_LIGHT_IMPERSONATE", "light.impersonate"),
        ("HLTV_LIGHT_JA4", "light.sync_ja4"),
        ("HLTV_RATE_PER_HOUR", "rate_limit.requests_per_hour"),
        ("HLTV_RATE_PER_DAY", "rate_limit.requests_per_day"),
        ("HLTV_RATE_BRAIN", "rate_limit.use_survival_brain"),
        ("HLTV_RATE_CONTENT_DETECT", "rate_limit.content_change_detection"),
        ("HLTV_API_PORT", "api_port"),
        ("HLTV_LOG_LEVEL", "logging.level"),
        ("HLTV_LOG_FILE", "logging.file"),
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


def load_settings(mode: str | None = None, config_path: str | None = None) -> HLTVSettings:
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
    "HLTVSettings", "ProfileSettings", "StealthSettings",
    "LightSettings", "BehaviorSettings", "RateLimitSettings",
    "LoggingSettings", "load_settings",
]
