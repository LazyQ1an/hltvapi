"""
HTML parsing utilities for HLTV pages (v3.5+ compatibility).

Provides helper functions for extracting common data patterns from
BeautifulSoup/selectolax parse trees.

Kept from old parser.py for backward compatibility.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup, Tag


# ── Timestamp patterns ──────────────────────────────────────────────

_RE_TIMESTAMP_RELATIVE = re.compile(r"(\d+)\s*(mins|hours|days|weeks|months|years?)\s*ago")
_RE_TIMESTAMP_ABSOLUTE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_RE_TIMESTAMP_HLTV = re.compile(
    r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\s+(\d{1,2}):(\d{2})",
)

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_relative_time(text: str) -> int | None:
    m = _RE_TIMESTAMP_RELATIVE.match(text.lower().strip())
    if not m:
        return None
    value = int(m.group(1))
    unit = m.group(2).rstrip("s")
    multipliers = {
        "min": 60, "hour": 3600, "day": 86400,
        "week": 604800, "month": 2_592_000, "year": 31_536_000,
    }
    multiplier = multipliers.get(unit)
    if multiplier is None:
        return None
    import time
    return int(time.time()) - (value * multiplier)


def parse_date_string(text: str) -> datetime | None:
    text = text.strip()
    now_dt = datetime.now()
    if text.lower().startswith("today"):
        time_part = text.split(None, 1)[-1] if len(text.split()) > 1 else "00:00"
        for fmt in ("%H:%M", "%I:%M %p"):
            try:
                t = datetime.strptime(time_part, fmt).time()
                return datetime.combine(now_dt.date(), t)
            except ValueError:
                continue
        return now_dt
    if text.lower().startswith("yesterday"):
        from datetime import timedelta
        yesterday = now_dt - timedelta(days=1)
        time_part = text.split(None, 1)[-1] if len(text.split()) > 1 else "00:00"
        for fmt in ("%H:%M", "%I:%M %p"):
            try:
                t = datetime.strptime(time_part, fmt).time()
                return datetime.combine(yesterday.date(), t)
            except ValueError:
                continue
        return yesterday
    m = _RE_TIMESTAMP_ABSOLUTE.match(text)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _RE_TIMESTAMP_HLTV.match(text)
    if m:
        return datetime(
            int(m.group(3)), int(m.group(2)), int(m.group(1)),
            int(m.group(4)), int(m.group(5)),
        )
    try:
        return datetime.strptime(text, "%b %d, %Y")
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%b %d %Y")
    except ValueError:
        pass
    return None


# ── HTML extraction helpers ────────────────────────────────────────


def safe_text(tag: Tag | Any | None, default: str = "", separator: str = " ") -> str:
    if tag is None:
        return default
    if hasattr(tag, "text") and not hasattr(tag, "get_text"):
        return tag.text(separator=separator, strip=True) if callable(getattr(tag, "text")) else str(getattr(tag, "text", default))
    return tag.get_text(separator=separator, strip=True)


def safe_int(text: str | None, default: int | None = None) -> int | None:
    if text is None:
        return default
    text = text.strip().replace(",", "").replace(" ", "")
    try:
        return int(text)
    except (ValueError, TypeError):
        return default


def safe_float(text: str | None, default: float | None = None) -> float | None:
    if text is None:
        return default
    text = text.strip().replace(",", "").replace(" ", "")
    try:
        return float(text)
    except (ValueError, TypeError):
        return default


def extract_href(tag: Tag | Any | None, default: str | None = None) -> str | None:
    if tag is None:
        return default
    if hasattr(tag, "attributes"):
        return tag.attributes.get("href", default)
    href = tag.get("href")
    if href is None:
        return default
    return str(href)


def extract_src(tag: Tag | Any | None, default: str | None = None) -> str | None:
    if tag is None:
        return default
    if hasattr(tag, "attributes"):
        return tag.attributes.get("src", default)
    src = tag.get("src")
    if src is None:
        return default
    return str(src)


def extract_img_url(tag: Tag | Any | None, default: str | None = None) -> str | None:
    if tag is None:
        return default
    if hasattr(tag, "attributes"):
        src = tag.attributes.get("src")
        if src:
            return str(src)
        data_src = tag.attributes.get("data-src") or tag.attributes.get("data-lazy-src")
        if data_src:
            return str(data_src)
        style = tag.attributes.get("style", "")
        bg_match = re.search(r"background-image:\s*url\(['\"]?(.+?)['\"]?\)", str(style))
        if bg_match:
            return bg_match.group(1)
        return default
    src = tag.get("src")
    if src:
        return str(src)
    data_src = tag.get("data-src") or tag.get("data-lazy-src")
    if data_src:
        return str(data_src)
    style = tag.get("style", "")
    bg_match = re.search(r"background-image:\s*url\(['\"]?(.+?)['\"]?\)", str(style))
    if bg_match:
        return bg_match.group(1)
    return default


def make_absolute_url(href: str | None, base: str = "https://www.hltv.org") -> str | None:
    if href is None:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return f"https:{href}"
    return f"{base}{href}" if href.startswith("/") else f"{base}/{href}"


def find_substring_between(text: str, start: str, end: str) -> str | None:
    s = text.find(start)
    if s == -1:
        return None
    s += len(start)
    e = text.find(end, s)
    if e == -1:
        return None
    return text[s:e]


# ── ID extraction helpers ─────────────────────────────────────────


def parse_team_id_from_url(url: str | None) -> int | None:
    if url is None:
        return None
    m = re.search(r"/team/(\d+)/", url)
    return int(m.group(1)) if m else None


def parse_player_id_from_url(url: str | None) -> int | None:
    if url is None:
        return None
    m = re.search(r"/player/(\d+)/", url)
    return int(m.group(1)) if m else None


def parse_event_id_from_url(url: str | None) -> int | None:
    if url is None:
        return None
    m = re.search(r"/events/(\d+)/", url)
    return int(m.group(1)) if m else None


def parse_match_id_from_url(url: str | None) -> int | None:
    if url is None:
        return None
    m = re.search(r"/matches/(\d+)/", url)
    return int(m.group(1)) if m else None


def _wrap_node(node: Any | None) -> Any | None:
    if node is None:
        return None
    if hasattr(node, "get") or not hasattr(node, "attributes"):
        return node
    original_attrs = node.attributes

    class SelectolaxAdapter:
        def __getattr__(self, name: str) -> Any:
            return getattr(node, name)

        def get(self, key: str, default: Any = None) -> Any:
            return original_attrs.get(key, default)

        def get_text(self, separator: str = " ", strip: bool = True) -> str:
            text = node.text(separator=separator) if callable(getattr(node, "text", None)) else str(node)
            return text.strip() if strip else text

        def __str__(self) -> str:
            return str(node)

        def __repr__(self) -> str:
            return repr(node)

    return SelectolaxAdapter()


def select_one(soup: BeautifulSoup | Tag | Any | None, selector: str) -> Tag | Any | None:
    if soup is None:
        return None
    css_first = getattr(soup, "css_first", None)
    if css_first is not None and callable(css_first):
        return _wrap_node(css_first(selector))
    result = soup.select_one(selector)
    return result


def select_all(soup: BeautifulSoup | Tag | Any | None, selector: str) -> list[Tag] | list[Any]:
    if soup is None:
        return []
    css = getattr(soup, "css", None)
    if css is not None and callable(css):
        result = css(selector)
        if result is None:
            return []
        return [_wrap_node(n) for n in result]
    return soup.select(selector)
