"""
Semantic honeypot detector for Cloudflare + HLTV anti-bot patterns. v8.0

Cloudflare hides honeypot elements in pages that real users never see
but crawlers often parse:
- Hidden form fields (display:none, visibility:hidden, opacity:0)
- Decoy links (positioned off-screen at -9999px)
- Fake input fields (type=hidden with tracking names)
- Invisible iframes
- Comment-based traps

This module scans page content for these patterns before data extraction
and raises alerts when honeypots are detected, allowing the system to
back off before triggering a hard block.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("hltv.antibot.honeypot")


# Known Cloudflare honeypot patterns
HONEYPOT_PATTERNS = [
    # Hidden form fields (classic CF honeypot)
    'input[type="hidden"][name*="cf"], input[type="hidden"][name*="_chk"]',
    'input[type="hidden"][name*="token"][style*="display"], input[type="hidden"][name*="csrf"][style*="display"]',

    # Off-screen elements
    '[style*="position: absolute"][style*="left: -9999"]',
    '[style*="position:absolute;left:-9999px"]',
    '[style*="left: -9999px"]',

    # Invisible iframes
    'iframe[style*="display: none"], iframe[style*="display:none"]',
    'iframe[style*="visibility: hidden"]',

    # Opacity-zero elements
    '[style*="opacity: 0"], [style*="opacity:0"]',

    # 1x1 tracking pixels
    'img[width="1"][height="1"]',

    # Suspicious aria-hidden content
    '[aria-hidden="true"][style*="position: absolute"]',

    # Form honeypots (fields real users can't see)
    'input[name="website"][tabindex="-1"], input[name="url"][tabindex="-1"]',
    'input[name="email2"], input[name="confirm_email"]',
]

# Known HLTV-specific detection patterns
HLTV_PATTERNS = [
    # CF challenge container
    'div[id*="cf-challenge"], div[class*="cf-challenge"]',
    'div[id*="turnstile"], div[class*="turnstile"]',

    # Bot detection scripts
    'script[src*="challenges.cloudflare.com"]',
    'script[src*="cloudflareinsights.com"]',

    # Meta refresh traps
    'meta[http-equiv="refresh"][content*="url="]',
]


class HoneypotDetector:
    """Scans page content for honeypot and detection patterns.

    Usage:
        detector = HoneypotDetector()
        result = await detector.scan(page_html)
        if result["honeypots_found"]:
            # Back off, don't parse this page
            logger.warning("Honeypot detected: %s", result["details"])
    """

    def __init__(self) -> None:
        self._stats: dict[str, int] = {
            "pages_scanned": 0,
            "honeypots_found": 0,
            "cf_challenges": 0,
            "false_positives": 0,
        }

    async def scan(self, html: str) -> dict[str, Any]:
        """Scan HTML content for honeypots.

        Returns dict with:
        - honeypots_found: whether any were detected
        - details: list of found patterns
        - threat_level: 'none', 'low', 'medium', 'high'
        - recommendation: action to take
        """
        self._stats["pages_scanned"] += 1

        if not html or len(html) < 500:
            return {
                "honeypots_found": True,
                "details": ["empty_or_too_small"],
                "threat_level": "high",
                "recommendation": "blocked_or_empty",
            }

        lower = html.lower()
        details: list[str] = []

        # Check CF honeypot patterns
        for pattern in HONEYPOT_PATTERNS:
            # Simple substring matching (we use DOM in real use, but HTML
            # scanning is faster for pre-filtering)
            if _pattern_in_html(pattern.lower(), lower):
                details.append(f"honeypot:{pattern[:50]}")

        # Check HLTV-specific patterns
        cf_found = False
        for pattern in HLTV_PATTERNS:
            if _pattern_in_html(pattern.lower(), lower):
                details.append(f"hlvt_block:{pattern[:50]}")
                cf_found = True

        if cf_found:
            self._stats["cf_challenges"] += 1

        if details:
            self._stats["honeypots_found"] += 1

        # Threat level assessment
        threat = "none"
        recommendation = "proceed"

        if cf_found and _has_block_keywords(lower):
            threat = "high"
            recommendation = "abort_and_sleep"
        elif cf_found:
            threat = "medium"
            recommendation = "cautious_proceed"
        elif details:
            threat = "low"
            recommendation = "proceed_with_care"

        return {
            "honeypots_found": len(details) > 0,
            "details": details,
            "threat_level": threat,
            "recommendation": recommendation,
        }

    def has_hltv_content(self, html: str) -> bool:
        """Check if page actually contains HLTV content (not a block page)."""
        if not html:
            return False
        lower = html.lower()
        markers = [
            "hltv", "nav-bar", "standard-box", "match-wrapper",
            "teamsBox", "topnav", "sidebar", "footer-navigation",
        ]
        return any(m.lower() in lower for m in markers)

    def get_stats(self) -> dict[str, Any]:
        return dict(self._stats)


def _pattern_in_html(pattern: str, html_lower: str) -> bool:
    """Check if a simplified CSS-like pattern appears in HTML."""
    # Extract key tokens from the pattern
    tokens = pattern.replace("[", " ").replace("]", " ").replace('"', " ").replace("'", " ").replace("=", " ").replace("*", "").replace(",", " ").split()
    # Filter short tokens
    tokens = [t for t in tokens if len(t) > 2 and t not in ("input", "type", "style", "name", "img", "div", "id", "class", "css")]
    # All key tokens must be present
    return all(t in html_lower for t in tokens)


def _has_block_keywords(html_lower: str) -> bool:
    """Check for explicit block/challenge keywords."""
    keywords = [
        "just a moment", "checking your browser",
        "cf-browser-verification", "__cf_chl_f_tk",
        "challenge-platform", "turnstile",
        "captcha", "blocked", "access denied",
    ]
    return any(k in html_lower for k in keywords)


__all__ = ["HoneypotDetector", "HONEYPOT_PATTERNS", "HLTV_PATTERNS"]
