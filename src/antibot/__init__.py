"""Anti-bot and anti-detection modules for single-IP Cloudflare bypass."""

from .rate_limiter import AdaptiveRateLimiter
from .block_detector import BlockDetector
from .human_pattern import HumanRequestPattern
from .header_profiles import (
    HeaderProfile,
    HEADER_PROFILES,
    random_profile,
    random_referer,
    random_accept_language,
)
from .fingerprint_spoofer import (
    build_full_stealth_script,
    build_canvas_spoof_script,
    build_webgl_spoof_script,
    build_audio_spoof_script,
    build_navigator_spoof_script,
    compute_ja4,
    BROWSER_JA4_SIGNATURES,
)

__all__ = [
    "AdaptiveRateLimiter",
    "BlockDetector",
    "HumanRequestPattern",
    "HeaderProfile",
    "HEADER_PROFILES",
    "random_profile",
    "random_referer",
    "random_accept_language",
    "build_full_stealth_script",
    "build_canvas_spoof_script",
    "build_webgl_spoof_script",
    "build_audio_spoof_script",
    "build_navigator_spoof_script",
    "compute_ja4",
    "BROWSER_JA4_SIGNATURES",
]