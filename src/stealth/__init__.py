"""Stealth Nodriver transport layer."""

from .browser import BrowserManager, CDP_CLEANUP_SCRIPT
from .simulator import HumanBehaviorSimulator
from .behavior_v2 import HumanBehaviorV2, BehaviorProfile
from .fingerprint_factory import FingerprintFactory, HardwareProfile, GPU_PROFILES, FONT_STACKS
from .cdp_patches import CDP_DEEP_CLEANUP, CDP_NAVIGATION_BLOCK, CDP_FULL_ARMOR
from .worker_injector import WorkerInjector, CROSS_CONTEXT_TIMING_SCRIPT, WORKER_FINGERPRINT_SCRIPT
from .behavior_v3 import MicroPhysicsMouse, CompletePointerEvents, HumanBehaviorV3

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
    "WorkerInjector",
    "CROSS_CONTEXT_TIMING_SCRIPT",
    "WORKER_FINGERPRINT_SCRIPT",
    "MicroPhysicsMouse",
    "CompletePointerEvents",
    "HumanBehaviorV3",
]
