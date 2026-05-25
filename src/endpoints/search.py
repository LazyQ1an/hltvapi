"""
Search endpoints for HLTV global search functionality.

HLTV search returns JSON data via the search endpoint:
  GET /search?term=<query>

Response is a JSON array of objects, each containing categorized results:
  [{
    "players": [...],
    "teams": [...],
    "matches": [...],
    "events": [...]
  }]
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.client import HLTVClient
from src.models.player import PlayerDetailed
from src.models.team import TeamDetail
from src.models.match import MatchOverview, MatchTeam
from src.models.event import EventOverview
from src.models.common import Event, Team
from src.utils.logger import get_logger

logger = get_logger("endpoints.search")


class SearchEndpoint:
    """Endpoints for global search on HLTV."""

    BASE_URL = "https://www.hltv.org"

    def __init__(self, client: HLTVClient) -> None:
        self._client = client

    async def search(self, query: str) -> dict[str, list[Any]]:
        """Perform a global search on HLTV.

        HLTV search returns JSON with categorized results.

        Args:
            query: Search query string.

        Returns:
            Dictionary of result categories to list of model objects.
        """
        url = f"{self.BASE_URL}/search?term={query.replace(' ', '+')}"
        html = await self._client.get(url)

        results: dict[str, list[Any]] = {
            "players": [],
            "teams": [],
            "matches": [],
            "events": [],
            "news": [],
            "other": [],
        }

        try:
            data = json.loads(html)
        except json.JSONDecodeError:
            logger.warning("Search returned non-JSON response for query: %s", query)
            return results

        if isinstance(data, list):
            data = data[0] if data else {}

        if not isinstance(data, dict):
            return results

        for player_data in data.get("players", []):
            try:
                player = PlayerDetailed(
                    id=player_data.get("id"),
                    name=player_data.get("nickName", ""),
                    real_name=self._build_real_name(
                        player_data.get("firstName", ""),
                        player_data.get("lastName", ""),
                    ),
                    photo=player_data.get("pictureUrl"),
                    country=self._extract_country(player_data.get("flagUrl", "")),
                    team=Team(name=player_data.get("team", {}).get("name", "")),
                )
                results["players"].append(player)
            except Exception as e:
                logger.debug("Failed to parse search player: %s", e)
                continue

        for team_data in data.get("teams", []):
            try:
                team = TeamDetail(
                    id=team_data.get("id"),
                    name=team_data.get("name", ""),
                    logo=team_data.get("teamLogoDay") or team_data.get("teamLogo"),
                    country=team_data.get("countryCode"),
                    rank=team_data.get("currentRanking"),
                )
                results["teams"].append(team)
            except Exception as e:
                logger.debug("Failed to parse search team: %s", e)
                continue

        for match_data in data.get("matches", []):
            try:
                match = MatchOverview(
                    id=match_data.get("id", 0),
                    team1=MatchTeam(name=match_data.get("team1", {}).get("name", "")),
                    team2=MatchTeam(name=match_data.get("team2", {}).get("name", "")),
                    event=Event(name=match_data.get("event", {}).get("name", "")),
                )
                results["matches"].append(match)
            except Exception as e:
                logger.debug("Failed to parse search match: %s", e)
                continue

        for event_data in data.get("events", []):
            try:
                event = EventOverview(
                    id=event_data.get("id"),
                    name=event_data.get("name", ""),
                    logo=event_data.get("logo"),
                )
                results["events"].append(event)
            except Exception as e:
                logger.debug("Failed to parse search event: %s", e)
                continue

        return results

    async def search_players(self, query: str) -> list[Any]:
        """Search only for players.

        Args:
            query: Player name or partial name.

        Returns:
            List of matching player results.
        """
        results = await self.search(query)
        return results.get("players", [])

    async def search_teams(self, query: str) -> list[Any]:
        """Search only for teams.

        Args:
            query: Team name or partial name.

        Returns:
            List of matching team results.
        """
        results = await self.search(query)
        return results.get("teams", [])

    @staticmethod
    def _extract_country(flag_url: str) -> str | None:
        """Extract country code from flag URL."""
        if not flag_url:
            return None
        m = re.search(r"/([A-Z]{2})\.\w+$", flag_url)
        return m.group(1) if m else None

    @staticmethod
    def _build_real_name(first: str, last: str) -> str | None:
        """Build real name from first and last name."""
        name = "{} {}".format(first, last).strip()
        return name if name else None


__all__ = ["SearchEndpoint"]
