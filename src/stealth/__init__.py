"""Stealth Nodriver transport layer."""

from .browser import BrowserManager, CDP_CLEANUP_SCRIPT
from .simulator import HumanBehaviorSimulator
from .behavior_v2 import HumanBehaviorV2, BehaviorProfile
from .fingerprint_factory import FingerprintFactory, HardwareProfile, GPU_PROFILES, FONT_STACKS
from .cdp_patches import CDP_DEEP_CLEANUP, CDP_NAVIGATION_BLOCK, CDP_FULL_ARMOR

__all__ = [
    "BrowserManager",
    "CDP_CLEANUP_SCRIPT",
    "CDP_DEEP_CLEANUP",
    "CDP_NAVIGATION_BLOCK",
    "CDP_FULL_ARMOR",
    "HumanBehaviorSimulator",
    "HumanBehaviorV2",
    "BehaviorProfile",
    "FingerprintFactory",
    "HardwareProfile",
    "GPU_PROFILES",
    "FONT_STACKS",
]
