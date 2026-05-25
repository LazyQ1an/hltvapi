"""
Parse success rate tracking for endpoint parsers.

Helps monitor when HLTV's page structure changes by tracking
what percentage of elements are successfully parsed.
"""

from __future__ import annotations

import logging
from typing import Any
from dataclasses import dataclass

logger = logging.getLogger("hltv.parsestats")


@dataclass
class ParseStats:
    """Tracks parse success/failure counts for an endpoint.

    Usage:
        stats = ParseStats("matches.upcoming")
        for element in elements:
            with stats.record():
                parse_element(element)
        stats.report()  # logs warning if ratio < 0.85
    """

    name: str
    """Name of the parser (e.g., 'matches.upcoming')."""

    total: int = 0
    """Total items attempted to parse."""

    success: int = 0
    """Items successfully parsed."""

    failure: int = 0
    """Items that failed to parse."""

    warning_threshold: float = 0.85
    """Minimum acceptable parse ratio before warning."""

    def record(self, success: bool = True) -> None:
        """Record a parse attempt result."""
        self.total += 1
        if success:
            self.success += 1
        else:
            self.failure += 1

    def record_context(self) -> "_ParseRecordContext":
        """Get a context manager that records success/failure."""
        return _ParseRecordContext(self)

    @property
    def ratio(self) -> float:
        """Parse success ratio (0.0 - 1.0)."""
        if self.total == 0:
            return 1.0
        return self.success / self.total

    def report(self) -> float:
        """Log a warning if parse ratio is below threshold.

        Returns:
            Current parse ratio.
        """
        r = self.ratio
        if r < self.warning_threshold:
            logger.warning(
                "Parse ratio LOW [%s]: %.1f%% (%d/%d success). "
                "HLTV may have changed page structure.",
                self.name, r * 100, self.success, self.total,
            )
        else:
            logger.debug(
                "Parse ratio OK [%s]: %.1f%% (%d/%d)",
                self.name, r * 100, self.success, self.total,
            )
        return r

    def reset(self) -> None:
        """Reset all counters."""
        self.total = 0
        self.success = 0
        self.failure = 0

    def snapshot(self) -> dict[str, Any]:
        """Get a snapshot of current stats for monitoring."""
        return {
            "name": self.name,
            "total": self.total,
            "success": self.success,
            "failure": self.failure,
            "ratio": self.ratio,
        }


class _ParseRecordContext:
    """Context manager for recording parse success/failure."""

    def __init__(self, stats: ParseStats) -> None:
        self._stats = stats

    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type: type | None, *args: object) -> None:
        if exc_type is None:
            self._stats.record(success=True)
        else:
            self._stats.record(success=False)
        # Don't suppress exceptions -- return implicit None


# Global registry of all parse stats for monitoring
_stats_registry: dict[str, ParseStats] = {}


def get_parse_stats(name: str) -> ParseStats:
    """Get or create a ParseStats instance by name."""
    if name not in _stats_registry:
        _stats_registry[name] = ParseStats(name)
    return _stats_registry[name]


def report_all() -> dict[str, dict[str, int | float]]:
    """Report parse stats for all registered parsers.

    Returns:
        Dict mapping parser names to their stats snapshots.
    """
    results: dict[str, dict[str, int | float]] = {}
    for name, stats in _stats_registry.items():
        stats.report()
        results[name] = stats.snapshot()
    return results
