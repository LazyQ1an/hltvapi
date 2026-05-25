"""
HLTV HTML parsing utilities.

Provides:
- Parser auto-detection (selectolax vs BeautifulSoup)
- HTML extraction helpers (safe_text, select_one, select_all, etc.)
- SemanticParser (multi-selector fallback)
- ParserPipeline (multi-stage parsing)
"""

from __future__ import annotations

from .helpers import (
    _wrap_node,
    extract_href,
    extract_img_url,
    extract_src,
    find_substring_between,
    make_absolute_url,
    parse_date_string,
    parse_event_id_from_url,
    parse_match_id_from_url,
    parse_player_id_from_url,
    parse_relative_time,
    parse_team_id_from_url,
    safe_float,
    safe_int,
    safe_text,
    select_all,
    select_one,
)

from .semantic import SemanticParser, SelectorStrategy
from .pipeline import ParserPipeline

_HAS_SELECTOLAX = False
try:
    import selectolax.parser  # noqa: F401
    _HAS_SELECTOLAX = True
except ImportError:
    pass

__all__ = [
    "_HAS_SELECTOLAX",
    "safe_text", "safe_int", "safe_float",
    "extract_href", "extract_img_url", "extract_src",
    "make_absolute_url", "find_substring_between",
    "parse_relative_time", "parse_date_string",
    "parse_team_id_from_url", "parse_player_id_from_url",
    "parse_event_id_from_url", "parse_match_id_from_url",
    "select_one", "select_all", "_wrap_node",
    "SemanticParser", "SelectorStrategy",
    "ParserPipeline",
]
