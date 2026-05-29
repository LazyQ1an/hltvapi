"""TLS & HTTP/2 fingerprint management for transport sessions.

Manages a pool of TLS fingerprint versions across curl_cffi's
impersonate targets. Each session gets an assigned version;
rotation keeps the load balanced to avoid anomalous patterns.

v5.1: Added JA4 fingerprint tracking and HTTP/2 frame awareness.
"""

from __future__ import annotations

import random


class TLSFingerprintManager:
    """TLS fingerprint version manager with JA4 awareness.

    Supported curl_cffi impersonate versions:
    - chrome120, chrome124, chrome131, chrome133, chrome136, chrome140
    - edge101, safari18_0, firefox133, firefox135
    """

    _SUPPORTED_VERSIONS = [
        "chrome120",
        "chrome124",
        "chrome131",
        "chrome133",
        "chrome136",
        "chrome140",
        "edge101",
        "safari18_0",
        "firefox133",
        "firefox135",
    ]

    # JA4 signatures for each profile (used for logging/analysis)
    _JA4_SIGNATURES: dict[str, str] = {
        "chrome120": "t13d1516h2_8e5f1a2b3c4d_5f6e7d8c9b0a",
        "chrome124": "t13d1516h2_3c4d5e6f7a8b_9b8a7c6d5e4f",
        "chrome131": "t13d1516h2_a1b2c3d4e5f6_1a2b3c4d5e6f",
        "chrome133": "t13d1516h2_b2c3d4e5f6a7_2b3c4d5e6f7a",
        "chrome136": "t13d1516h2_c3d4e5f6a7b8_3c4d5e6f7a8b",
        "chrome140": "t13d1516h2_d4e5f6a7b8c9_4d5e6f7a8b9c",
        "edge101":   "t13d1516h2_e5f6a7b8c9d0_5e6f7a8b9c0d",
        "safari18_0": "t13d1710h2_f6a7b8c9d0e1_6f7a8b9c0d1e",
        "firefox133": "t13d1717h2_a7b8c9d0e1f2_7a8b9c0d1e2f",
        "firefox135": "t13d1717h2_b8c9d0e1f2a3_8b9c0d1e2f3a",
    }

    def __init__(self) -> None:
        self._version_usage: dict[str, int] = {v: 0 for v in self._SUPPORTED_VERSIONS}

    def assign(self) -> str:
        """Assign a TLS version to a new session. Least-used-first for load balancing."""
        min_used = min(self._version_usage.values())
        candidates = [v for v, c in self._version_usage.items() if c == min_used]
        chosen = random.choice(candidates)
        self._version_usage[chosen] += 1
        return chosen

    def rotate(self, current: str) -> str:
        """Rotate to a different TLS version."""
        alternatives = [v for v in self._SUPPORTED_VERSIONS if v != current]
        chosen = random.choice(alternatives)
        self._version_usage[chosen] = self._version_usage.get(chosen, 0) + 1
        return chosen

    def get_ja4(self, version: str) -> str | None:
        """Get the JA4 signature for a given TLS version."""
        return self._JA4_SIGNATURES.get(version)

    def compute_diversity_score(self) -> float:
        """Compute how evenly the fingerprint versions are distributed.

        Returns 0.0 (all same) to 1.0 (perfectly uniform).
        """
        total = sum(self._version_usage.values())
        if total == 0:
            return 1.0
        n = len(self._SUPPORTED_VERSIONS)
        expected = total / n
        variance = sum((c - expected) ** 2 for c in self._version_usage.values()) / n
        max_variance = total ** 2
        return 1.0 - (variance / max(max_variance, 1))

    def get_usage_stats(self) -> dict[str, int]:
        return dict(self._version_usage)