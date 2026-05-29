"""Anti-detection modules."""

from .block_detector import BlockDetector
from .fatigue_tracker import FatigueTracker, FatigueMetrics
from .fingerprint_spoofer import (
    build_full_stealth_script,
    build_canvas_spoof_script,
    build_webgl_spoof_script,
    build_audio_spoof_script,
    build_navigator_spoof_script,
    compute_ja4,
    BROWSER_JA4_SIGNATURES,
)
from .header_profiles import HeaderProfile, random_profile, random_referer
from .human_pattern import HumanRequestPattern
from .rate_limiter import AdaptiveRateLimiter

__all__ = [
    "BlockDetector",
    "FatigueTracker",
    "FatigueMetrics",
    "build_full_stealth_script",
    "build_canvas_spoof_script",
    "build_webgl_spoof_script",
    "build_audio_spoof_script",
    "build_navigator_spoof_script",
    "compute_ja4",
    "BROWSER_JA4_SIGNATURES",
    "HeaderProfile",
    "random_profile",
    "random_referer",
    "HumanRequestPattern",
    "AdaptiveRateLimiter",
]
