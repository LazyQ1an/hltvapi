"""
Content-driven behavioural timing — replacing random delays with DOM-informed
"reading time" estimates. v9.0

Instead of blind random sleeps between requests, this module parses the
returned HTML to estimate how long a human would actually spend reading
the content. Key insight: human dwell time correlates with text density,
data complexity (tables/lists), and navigation intent — not random jitter.

Cloudflare's behavioural models score sessions on traversing semantics:
a bot clicks through 50 detail pages in 3 seconds each; a human pauses
proportionally to the information on each page.

Components:
- TextDensityAnalyzer: count words, tables, lists, paragraphs
- ReadingTimeEstimator: convert density metrics → seconds
- AttentionModel: decide which page regions matter most
- ContentDrivenDelay: unified interface returning asyncio sleep duration
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass

logger = logging.getLogger("hltv.stealth.content_timing")


# ---------------------------------------------------------------------------
# Text density metrics
# ---------------------------------------------------------------------------

@dataclass
class ContentMetrics:
    """Measured complexity of a returned HTML page."""
    word_count: int = 0
    table_count: int = 0
    list_item_count: int = 0
    link_count: int = 0
    heading_count: int = 0
    image_count: int = 0
    form_element_count: int = 0
    raw_byte_length: int = 0

    @property
    def density_score(self) -> float:
        """Composite 0-1 score where 1 = very dense content."""
        w = min(1.0, self.word_count / 2000.0)
        t = min(1.0, self.table_count / 15.0)
        li = min(1.0, self.list_item_count / 40.0)
        return round(0.45 * w + 0.30 * t + 0.15 * li + 0.10 * min(1.0, self.heading_count / 8.0), 3)


# ---------------------------------------------------------------------------
# Text density analysis
# ---------------------------------------------------------------------------

_SIMPLE_TAG = re.compile(r"<\s*(\w+)[^>]*>", re.IGNORECASE)
_SCRIPT_STYLE = re.compile(r"<(script|style|noscript|template)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_WHITESPACE = re.compile(r"\s+")


class TextDensityAnalyzer:
    """Parse HTML text to measure content density.

    Works on raw HTML strings — no DOM required. This makes it usable
    in both stealth (Nodriver) and light (curl_cffi) modes.
    """

    # Tags that carry semantic content weight
    _CONTENT_TAGS: set[str] = {"p", "span", "div", "td", "th", "li", "a", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "figcaption", "blockquote", "pre", "code", "label"}

    # Tags that indicate structured data
    _TABLE_TAGS: set[str] = {"table"}
    _LIST_TAGS: set[str] = {"li"}
    _LINK_TAGS: set[str] = {"a"}
    _HEADING_TAGS: set[str] = {"h1", "h2", "h3", "h4", "h5", "h6"}
    _IMAGE_TAGS: set[str] = {"img"}
    _FORM_TAGS: set[str] = {"input", "select", "textarea", "button"}

    def analyze(self, html: str) -> ContentMetrics:
        """Extract content density metrics from raw HTML."""
        if not html:
            return ContentMetrics()

        # Strip scripts, styles, comments
        clean = _SCRIPT_STYLE.sub("", html)
        clean = _HTML_COMMENT.sub("", clean)

        metrics = ContentMetrics(raw_byte_length=len(html))

        # Count structured elements by tag
        for match in _SIMPLE_TAG.finditer(clean):
            tag = match.group(1).lower()
            if tag in self._TABLE_TAGS:
                metrics.table_count += 1
            elif tag in self._LIST_TAGS:
                metrics.list_item_count += 1
            elif tag in self._LINK_TAGS:
                metrics.link_count += 1
            elif tag in self._HEADING_TAGS:
                metrics.heading_count += 1
            elif tag in self._IMAGE_TAGS:
                metrics.image_count += 1
            elif tag in self._FORM_TAGS:
                metrics.form_element_count += 1

        # Count words in visible text (crude: strip all tags, count word-like tokens)
        text_only = re.sub(r"<[^>]+>", " ", clean)
        text_only = _WHITESPACE.sub(" ", text_only).strip()
        metrics.word_count = len(text_only.split()) if text_only else 0

        return metrics


# ---------------------------------------------------------------------------
# Reading time estimator
# ---------------------------------------------------------------------------

class ReadingTimeEstimator:
    """Convert content metrics into human-plausible dwell times.

    Based on reading-speed research:
    - Average English reading speed: ~238 wpm (words per minute) for comprehension
    - Table scanning: ~3-8 seconds per table
    - List scanning: ~0.3-0.8 seconds per item
    - Image inspection: ~1-3 seconds per image
    - Navigation decision: 0.5-2 seconds per link (only a sample are considered)
    """

    # Baseline parameters (calibrated to realistic human behaviour)
    WORDS_PER_SECOND: float = 3.8        # ~228 wpm — comprehension reading
    TABLE_SCAN_SECONDS: float = 4.5       # average time to scan a data table
    LIST_ITEM_SECONDS: float = 0.45       # scan a single list item
    IMAGE_SECONDS: float = 1.8            # glance at an image
    NAVIGATION_OVERHEAD: float = 1.2      # base decision time

    # Content-type scaling factors
    LISTING_PAGE_FACTOR: float = 0.55     # match listings: scan, don't read
    DETAIL_PAGE_FACTOR: float = 1.0       # full-article reading
    STATS_PAGE_FACTOR: float = 0.75       # data-heavy: more scanning than reading

    def estimate(self, metrics: ContentMetrics, page_type: str = "detail") -> float:
        """Estimate reading time in seconds.

        Args:
            metrics: Measured content density.
            page_type: One of 'listing', 'detail', 'stats'.
        """
        if not metrics or metrics.word_count == 0:
            return random.uniform(1.5, 3.5)

        # Core reading time
        reading_time = metrics.word_count / self.WORDS_PER_SECOND

        # Structural scanning time
        table_time = metrics.table_count * self.TABLE_SCAN_SECONDS
        list_time = metrics.list_item_count * self.LIST_ITEM_SECONDS
        image_time = min(metrics.image_count, 15) * self.IMAGE_SECONDS

        # Navigation consideration (human samples ~10-20% of links consciously)
        nav_links = min(metrics.link_count, 80) * 0.15
        nav_time = nav_links * 0.3 + self.NAVIGATION_OVERHEAD

        raw = reading_time + table_time + list_time + image_time + nav_time

        # Apply page-type factor
        factor = {
            "listing": self.LISTING_PAGE_FACTOR,
            "detail": self.DETAIL_PAGE_FACTOR,
            "stats": self.STATS_PAGE_FACTOR,
        }.get(page_type, 1.0)

        scaled = raw * factor

        # Clamp to realistic human range
        lower = {"listing": 2.0, "detail": 5.0, "stats": 3.0}.get(page_type, 3.0)
        upper = {"listing": 15.0, "detail": 60.0, "stats": 30.0}.get(page_type, 30.0)

        return round(max(lower, min(upper, scaled)), 2)


# ---------------------------------------------------------------------------
# Attention model
# ---------------------------------------------------------------------------

@dataclass
class AttentionSegment:
    """A region of the page that draws human attention."""
    region: str           # 'header', 'main-table', 'sidebar', 'stats-block', 'footer'
    weight: float         # 0-1 attention weight
    dwell_seconds: float  # how long a human would focus here


class AttentionModel:
    """Model where a human's eyes would go on a given HLTV page.

    Different page types have different attention heatmaps:
    - Match page: scoreboard → map stats → player stats → event info → sidebar
    - Player page: stats table → team history → achievements → sidebar
    - Listing page: first 3-5 results → scroll → next batch
    """

    def compute_attention(
        self,
        metrics: ContentMetrics,
        page_type: str = "detail",
    ) -> list[AttentionSegment]:
        """Return ordered attention segments for a page."""
        segments: list[AttentionSegment] = []

        if page_type == "detail":
            # Main content dominates, then supporting data
            segments = [
                AttentionSegment("header", 0.10, random.uniform(1.0, 2.5)),
                AttentionSegment("main-content", 0.45, random.uniform(4.0, 12.0)),
            ]
            if metrics.table_count > 0:
                segments.append(AttentionSegment("stats-table", 0.25, random.uniform(2.0, 8.0)))
            if metrics.list_item_count > 5:
                segments.append(AttentionSegment("data-list", 0.12, random.uniform(1.5, 4.0)))
            segments.append(AttentionSegment("footer-sidebar", 0.08, random.uniform(0.5, 2.0)))

        elif page_type == "listing":
            segments = [
                AttentionSegment("header-filters", 0.08, random.uniform(0.5, 1.5)),
                AttentionSegment("results-list", 0.70, random.uniform(4.0, 12.0)),
                AttentionSegment("pagination", 0.12, random.uniform(1.0, 3.0)),
                AttentionSegment("sidebar", 0.10, random.uniform(0.5, 2.0)),
            ]

        elif page_type == "stats":
            segments = [
                AttentionSegment("header", 0.05, random.uniform(0.5, 1.5)),
                AttentionSegment("main-stats-block", 0.55, random.uniform(5.0, 15.0)),
                AttentionSegment("secondary-stats", 0.25, random.uniform(2.0, 6.0)),
                AttentionSegment("sidebar-comparison", 0.15, random.uniform(1.0, 3.5)),
            ]

        return segments


# ---------------------------------------------------------------------------
# Unified content-driven delay
# ---------------------------------------------------------------------------

class ContentDrivenDelay:
    """Replace random sleep with content-informed dwell timing.

    Usage:
        delay = ContentDrivenDelay()
        html = await client.get("https://www.hltv.org/matches/...")
        await delay.sleep(html, page_type="detail")

    The sleep duration is derived from the actual content retrieved,
    making the session's timing semantically coherent with what a
    human would actually do.
    """

    def __init__(self) -> None:
        self._analyzer = TextDensityAnalyzer()
        self._estimator = ReadingTimeEstimator()
        self._attention = AttentionModel()
        self._page_history: list[tuple[str, str, float]] = []  # (url, page_type, dwell)

    async def sleep(self, html: str, *, page_type: str = "detail", url: str = "") -> float:
        """Sleep for a content-driven duration. Returns seconds slept."""
        import asyncio

        metrics = self._analyzer.analyze(html)
        base = self._estimator.estimate(metrics, page_type)

        # Add micro-jitter (natural human variance: ~10-15% of base)
        jitter = base * random.uniform(-0.12, 0.15)
        dwell = round(max(0.5, base + jitter), 2)

        # Record for session-level coherence
        if url:
            self._page_history.append((url, page_type, dwell))
            if len(self._page_history) > 100:
                self._page_history = self._page_history[-50:]

        logger.debug("Content-driven sleep: %.1fs (words=%d tables=%d lists=%d density=%.2f type=%s)",
                     dwell, metrics.word_count, metrics.table_count,
                     metrics.list_item_count, metrics.density_score, page_type)

        await asyncio.sleep(dwell)
        return dwell

    @property
    def recent_average_dwell(self) -> float:
        """Average dwell time over recent pages, for session coherence."""
        if not self._page_history:
            return 5.0
        recent = self._page_history[-10:]
        return sum(d for _, _, d in recent) / len(recent)

    def get_metrics(self) -> ContentMetrics:
        """Return metrics for the most recently analyzed page."""
        return ContentMetrics()


__all__ = [
    "ContentMetrics",
    "TextDensityAnalyzer",
    "ReadingTimeEstimator",
    "AttentionModel",
    "AttentionSegment",
    "ContentDrivenDelay",
]
