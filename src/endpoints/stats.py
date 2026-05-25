"""
Statistics endpoints for HLTV.

Note: HLTV's /stats/ pages have additional Cloudflare protection and often
return 403 for automated requests. These endpoints handle failures gracefully.
"""

from __future__ import annotations

from typing import Any

from src.client import HLTVClient
from src.models.common import MapName
from src.parser import (
    safe_text, extract_href,
    make_absolute_url, select_one, select_all,
)
from src.utils.logger import get_logger
from src.exceptions import HTTPError, BlockedError

logger = get_logger("endpoints.stats")


class StatsEndpoint:
    """Endpoints for statistical data.

    Note: HLTV's stats section (/stats/) often triggers additional Cloudflare
    protections. These methods handle failures gracefully and return partial
    data when fully blocked.
    """

    BASE_URL = "https://www.hltv.org"

    def __init__(self, client: HLTVClient) -> None:
        self._client = client

    async def get_top_players_by_map(self, map_name: MapName | None = None) -> list[dict[str, Any]]:
        """Fetch top players for a specific map.

        Args:
            map_name: Filter by map.

        Returns:
            List of player stat entries.
        """
        url = f"{self.BASE_URL}/stats/players"
        if map_name and map_name != MapName.UNKNOWN:
            url += f"?map={map_name.value.lower()}"

        return await self._parse_stats_table(url)

    async def get_team_stats(self, team_id: int) -> dict[str, Any]:
        """Fetch statistics for a specific team.

        Args:
            team_id: HLTV team ID.

        Returns:
            Dictionary with team stats data.
        """
        url = f"{self.BASE_URL}/stats/team/{team_id}/-"
        return await self._parse_team_stats(url)

    async def _safe_fetch_soup(self, url: str) -> Any | None:
        """Try to fetch and parse a stats page, returning None if blocked."""
        try:
            return await self._client.get_soup(url)
        except (HTTPError, BlockedError) as e:
            logger.warning("Stats endpoint blocked for %s: %s", url, e)
            return None

    async def _parse_stats_table(self, url: str) -> list[dict[str, Any]]:
        """Parse a generic stats table from a stats page."""
        soup = await self._safe_fetch_soup(url)
        if soup is None:
            return []

        stats: list[dict[str, Any]] = []
        # Try multiple table selectors
        for table_sel in [".stats-table", "table.standard", ".table", "table"]:
            table = select_one(soup, table_sel)
            if table:
                rows = select_all(table, "tbody tr, tr")
                if len(rows) > 1:
                    # Get headers
                    header_row = select_one(table, "thead tr")
                    headers: list[str] = []
                    if header_row:
                        headers = [safe_text(h) for h in select_all(header_row, "th, td")]

                    for row in rows:
                        try:
                            cells = select_all(row, "td")
                            if not cells:
                                continue
                            entry: dict[str, Any] = {}
                            for i, cell in enumerate(cells):
                                text = safe_text(cell)
                                link = select_one(cell, "a")
                                href = extract_href(link) if link else None
                                
                                col_name = headers[i] if i < len(headers) else f"col_{i}"
                                entry[col_name] = {
                                    "text": text,
                                    "url": make_absolute_url(href) if href else None,
                                }
                            stats.append(entry)
                        except Exception as e:
                            logger.debug("Failed to parse stat row: %s", e)
                            continue
                    break  # Found and parsed a table
        return stats

    async def _parse_team_stats(self, url: str) -> dict[str, Any]:
        """Parse team-specific stats page."""
        soup = await self._safe_fetch_soup(url)
        if soup is None:
            return {"error": "Stats page blocked by Cloudflare"}

        stats_data: dict[str, Any] = {}

        # Try to find stat sections on the page
        for section_sel in [".stats-section", ".stat-group", ".row-stats", "section"]:
            sections = select_all(soup, section_sel)
            for section in sections:
                header = select_one(section, "h2, h3, .header, .section-title")
                section_name = safe_text(header) if header else "unknown"
                
                rows_data: list[dict[str, str]] = []
                tables = select_all(section, "table")
                if not tables:
                    # Try direct row parsing
                    items = select_all(section, ".stat-item, .row, .entry")
                    for item in items:
                        label = safe_text(select_one(item, ".label, .name, .stat-label"))
                        value = safe_text(select_one(item, ".value, .val, .stat-value"))
                        if label and value:
                            rows_data.append({label: value})
                else:
                    for table in tables:
                        for row in select_all(table, "tbody tr, tr"):
                            cells = select_all(row, "td, th")
                            if cells:
                                row_dict: dict[str, str] = {}
                                for i, cell in enumerate(cells):
                                    row_dict[f"col_{i}"] = safe_text(cell)
                                rows_data.append(row_dict)

                if rows_data:
                    stats_data[section_name] = rows_data

        return stats_data if stats_data else {"message": "No stat tables found"}


__all__ = ["StatsEndpoint"]
