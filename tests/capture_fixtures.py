"""
Capture live HTML snapshots from HLTV for use as test fixtures.

Run this script periodically (e.g., weekly) to keep test fixtures up-to-date
with HLTV's evolving page structure. When a test fails because of selector
changes, re-run this script to capture the new HTML, then update the selectors.

Usage:
    python tests/capture_fixtures.py

Requirements:
    curl_cffi must be installed: pip install curl-cffi
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


FIXTURES_DIR = Path(__file__).parent / "fixtures"

FIXTURES = [
    ("matches_page.html", "https://www.hltv.org/matches"),
    ("results_page.html", "https://www.hltv.org/results"),
    ("ranking_page.html", "https://www.hltv.org/ranking/teams"),
    ("match_detail.html", "https://www.hltv.org/matches/2394176/legacy-vs-gamerlegion-iem-atlanta-2026"),
    ("team_detail.html", "https://www.hltv.org/team/9565/vitality"),
]


async def capture() -> None:
    """Fetch each URL and save as fixture file."""
    from curl_cffi.requests import AsyncSession

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    session = AsyncSession(impersonate="chrome124", timeout=30)

    for filename, url in FIXTURES:
        print("Fetching {} -> {}...".format(url, filename))
        try:
            response = await session.get(url)
            path = FIXTURES_DIR / filename
            path.write_text(response.text, encoding="utf-8")
            print("  OK: {} bytes".format(len(response.text)))
        except Exception as e:
            print("  FAIL: {}".format(e))
        await asyncio.sleep(2)  # Be polite

    await session.close()
    print("\nFixtures captured in: {}".format(FIXTURES_DIR))
    print("Run tests: pytest tests/ -v")


if __name__ == "__main__":
    asyncio.run(capture())
