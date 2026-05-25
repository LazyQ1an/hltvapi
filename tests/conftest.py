"""
Pytest fixtures for HLTV scraper tests.

Provides:
- HTML snapshot fixtures from saved files
- A mock HLTVClient that returns HTML from files instead of making HTTP calls
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Load an HTML fixture file.

    Args:
        name: Fixture filename (e.g., 'matches_page.html').

    Returns:
        HTML content as string.
    """
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip("Fixture not found: {}".format(name))
    return path.read_text(encoding="utf-8")


@pytest.fixture
def matches_page_html() -> str:
    """HTML snapshot of the HLTV matches listing page."""
    return load_fixture("matches_page.html")


@pytest.fixture
def results_page_html() -> str:
    """HTML snapshot of the HLTV results page."""
    return load_fixture("results_page.html")


@pytest.fixture
def ranking_page_html() -> str:
    """HTML snapshot of the HLTV ranking page."""
    return load_fixture("ranking_page.html")


@pytest.fixture
def match_detail_html() -> str:
    """HTML snapshot of a match detail page."""
    return load_fixture("match_detail.html")


@pytest.fixture
def team_detail_html() -> str:
    """HTML snapshot of a team detail page."""
    return load_fixture("team_detail.html")
