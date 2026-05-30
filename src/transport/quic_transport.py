"""
HTTP/3 (QUIC) transport detection and upgrade tracking. NG1.0

Modern browsers visiting CDN-backed sites like HLTV automatically
upgrade to HTTP/3 after receiving an Alt-Svc header. A single IP that
persistently uses only TCP/HTTP2 over hours looks suspicious in
Cloudflare's protocol-weight model.

This module:
- Parses Alt-Svc response headers for QUIC/h3 advertisements
- Tracks per-domain H3 capability
- Maintains a protocol state machine (H2 → H3 upgrade)
- Feeds protocol freshness data into the survival brain scoring
- Integrates with TLSSessionManager for cross-mode session continuity

Note: curl_cffi's native QUIC support is limited. This module provides
the detection layer and informs the scheduler, but actual H3 transport
may require a native aioquic stack (future extension point).
"""

from __future__ import annotations

import logging
import re
import time as tmod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("hltv.transport.quic")


# ---------------------------------------------------------------------------
# Alt-Svc header parser
# ---------------------------------------------------------------------------

# Alt-Svc format: 'h3=":443"; ma=86400, h2=":443"; ma=7200'
_ALTSVC_RE = re.compile(
    r'(h3|h3-\d+|quic)\s*=\s*"([^"]*)"(?:\s*;\s*ma\s*=\s*(\d+))?',
    re.IGNORECASE,
)


@dataclass
class AltSvcAdvertisement:
    """Parsed Alt-Svc header entry."""
    protocol: str         # 'h3', 'h3-29', 'quic'
    authority: str        # ':443', ':8443'
    max_age: int          # seconds (default 86400)
    seen_at: float = field(default_factory=tmod.time)

    @property
    def is_quic(self) -> bool:
        return self.protocol.startswith("h3") or self.protocol == "quic"

    @property
    def expires_at(self) -> float:
        return self.seen_at + self.max_age


class AltSvcParser:
    """Parse Alt-Svc and Alt-Used response headers."""

    @staticmethod
    def parse(header_value: str) -> list[AltSvcAdvertisement]:
        """Parse an Alt-Svc header value into advertisements."""
        if not header_value:
            return []
        results: list[AltSvcAdvertisement] = []
        for match in _ALTSVC_RE.finditer(header_value):
            proto = match.group(1).lower()
            authority = match.group(2)
            ma = int(match.group(3)) if match.group(3) else 86400
            results.append(AltSvcAdvertisement(protocol=proto, authority=authority, max_age=ma))
        return results


# ---------------------------------------------------------------------------
# Per-domain H3 state
# ---------------------------------------------------------------------------

@dataclass
class DomainH3State:
    """Track HTTP/3 capability for a specific domain."""
    domain: str
    h3_supported: bool = False
    first_seen_h3: float = 0.0
    last_seen_h3: float = 0.0
    h3_endpoints: list[AltSvcAdvertisement] = field(default_factory=list)
    upgrade_attempts: int = 0
    upgrade_successes: int = 0

    @property
    def should_upgrade(self) -> bool:
        """Whether subsequent requests should use H3."""
        if not self.h3_supported:
            return False
        # Check if the most recent advertisement is still fresh
        if self.h3_endpoints:
            latest = max(self.h3_endpoints, key=lambda a: a.seen_at)
            return tmod.time() < latest.expires_at
        return False

    @property
    def freshness_score(self) -> float:
        """0-1 score of how "real browser" the protocol usage looks."""
        if not self.h3_supported:
            return 0.0
        # Recent H3 detection = high score
        age = tmod.time() - self.last_seen_h3
        if age < 60:
            return 1.0
        if age < 300:
            return 0.8
        if age < 1800:
            return 0.5
        return 0.2


# ---------------------------------------------------------------------------
# QUIC upgrade manager
# ---------------------------------------------------------------------------

class QUICUpgradeManager:
    """Manage HTTP/3 protocol upgrades per domain.

    Tracks which domains advertise H3 and whether the transport
    layer should attempt a QUIC connection on the next request.

    Usage:
        mgr = QUICUpgradeManager()

        # After getting a response:
        mgr.process_response_headers("www.hltv.org", response_headers)

        # Before making a request:
        if mgr.should_use_h3("www.hltv.org"):
            # use QUIC transport
    """

    def __init__(self, max_domains: int = 50) -> None:
        self._domains: dict[str, DomainH3State] = {}
        self._max_domains = max_domains
        self._parser = AltSvcParser()

    def process_response_headers(
        self,
        domain: str,
        headers: dict[str, str],
    ) -> None:
        """Extract Alt-Svc from response headers and update state."""
        state = self._get_or_create(domain)

        alt_svc = headers.get("alt-svc", "") or headers.get("Alt-Svc", "")
        if not alt_svc:
            return

        ads = self._parser.parse(alt_svc)
        quic_ads = [a for a in ads if a.is_quic]

        if quic_ads:
            if not state.h3_supported:
                logger.info("H3 detected for %s: %s", domain,
                            ", ".join(f"{a.protocol}={a.authority}" for a in quic_ads))
            state.h3_supported = True
            state.last_seen_h3 = tmod.time()
            if state.first_seen_h3 == 0:
                state.first_seen_h3 = tmod.time()
            state.h3_endpoints = quic_ads

    def should_use_h3(self, domain: str) -> bool:
        """Check if we should attempt QUIC for this domain."""
        state = self._domains.get(domain)
        if not state:
            return False
        return state.should_upgrade

    def get_freshness(self, domain: str) -> float:
        """Get protocol freshness score (0-1) for survival brain."""
        state = self._domains.get(domain)
        if not state:
            return 0.0
        return state.freshness_score

    def get_all_domains(self) -> list[DomainH3State]:
        """Return all tracked domain states."""
        return list(self._domains.values())

    def get_h3_capable_domains(self) -> list[str]:
        """Return domains known to support H3."""
        return [d for d, s in self._domains.items() if s.h3_supported]

    def get_stats(self) -> dict[str, Any]:
        """Return summary stats for monitoring."""
        h3 = self.get_h3_capable_domains()
        return {
            "domains_tracked": len(self._domains),
            "h3_capable_count": len(h3),
            "h3_domains": h3[:10],
            "avg_freshness": round(
                sum(s.freshness_score for s in self._domains.values()) / max(1, len(self._domains)),
                3,
            ),
        }

    def _get_or_create(self, domain: str) -> DomainH3State:
        if domain not in self._domains:
            if len(self._domains) >= self._max_domains:
                oldest = min(self._domains, key=lambda d: self._domains[d].last_seen_h3)
                del self._domains[oldest]
            self._domains[domain] = DomainH3State(domain=domain)
        return self._domains[domain]

    def mark_quic_success(self, domain: str) -> None:
        """Record a successful QUIC connection."""
        state = self._get_or_create(domain)
        state.upgrade_successes += 1
        state.upgrade_attempts += 1

    def mark_quic_failure(self, domain: str) -> None:
        """Record a failed QUIC attempt (fall back to H2)."""
        state = self._get_or_create(domain)
        state.upgrade_attempts += 1

    @property
    def quic_success_rate(self) -> float:
        """Overall QUIC upgrade success rate."""
        total = sum(s.upgrade_attempts for s in self._domains.values())
        if total == 0:
            return 0.0
        return sum(s.upgrade_successes for s in self._domains.values()) / total


__all__ = [
    "AltSvcAdvertisement",
    "AltSvcParser",
    "DomainH3State",
    "QUICUpgradeManager",
]
