"""
Player-related endpoints: player detail, top players, map stats.
"""
from __future__ import annotations
from bs4 import BeautifulSoup, Tag
from src.client import HLTVClient
from src.models.player import (
    PlayerDetailed, TopPlayer, TopPlayersResponse, PlayerMapStats,
)
from src.models.common import Team
from src.parser import (
    safe_text, safe_int, safe_float, extract_href, extract_img_url,
    parse_player_id_from_url, parse_team_id_from_url, select_one, select_all,
)
from src.utils.logger import get_logger

logger = get_logger("endpoints.players")

class PlayersEndpoint:
    """Endpoints for player-related data."""

    BASE_URL = "https://www.hltv.org"

    def __init__(self, client: HLTVClient) -> None:
        self._client = client

    async def get_detail(self, player_id: int) -> PlayerDetailed:
        """Fetch full player details.

        Args:
            player_id: HLTV player ID.

        Returns:
            PlayerDetailed with full statistics.
        """
        url = f"{self.BASE_URL}/player/{player_id}/-"
        soup = await self._client.get_soup(url)
        return self._parse_player_detail(soup, player_id)

    async def get_top_players(
        self,
        period: str = "last3months",
    ) -> TopPlayersResponse:
        """Fetch top player rankings for a given period.

        Args:
            period: Time period. One of:
                - 'last3months' (default)
                - 'last6months'
                - 'last12months'
                - 'alltime'
                - 'currentyear'
                - 'bigevents'

        Returns:
            TopPlayersResponse with ranked players.
        """
        valid_periods = {
            "last3months": "last3months",
            "last6months": "last6months",
            "last12months": "last12months",
            "alltime": "alltime",
            "currentyear": "thisyear",
            "bigevents": "bigevents",
        }
        param = valid_periods.get(period, "last3months")
        url = f"{self.BASE_URL}/stats/players?startDate={param}"
        soup = await self._client.get_soup(url)
        return self._parse_top_players(soup, period)

    async def get_map_stats(self, player_id: int) -> list[PlayerMapStats]:
        """Fetch per-map statistics for a player.

        Args:
            player_id: HLTV player ID.

        Returns:
            List of PlayerMapStats per map.
        """
        url = f"{self.BASE_URL}/player/{player_id}/-"
        soup = await self._client.get_soup(url)
        map_stats: list[PlayerMapStats] = []

        map_containers = select_all(soup, ".map-stat, .map-stats-item, .map-performance")
        for el in map_containers:
            try:
                from src.models.common import MapName
                map_el = select_one(el, ".map, .map-name")
                map_name_text = safe_text(map_el).strip().lower()
                map_name = MapName.UNKNOWN
                for map_enum in MapName:
                    if map_enum.value.lower() in map_name_text:
                        map_name = map_enum
                        break

                wr_el = select_one(el, ".win-rate, .percentage")
                wr_text = safe_text(wr_el)
                win_rate = (safe_float(wr_text.replace("%", "")) or 0.0) if wr_text else 0.0

                kd_el = select_one(el, ".kd, .kd-diff")
                kd = safe_float(safe_text(kd_el)) or 0.0

                rat_el = select_one(el, ".rating, .hltv-rating")
                rating = safe_float(safe_text(rat_el)) or 0.0

                wins = losses = 0
                wl_text = safe_text(select_one(el, ".wins-losses, .wl-record"))
                if wl_text:
                    import re
                    wl_match = re.search(r"(\d+)\s*[Ww]\s*/\s*(\d+)\s*[Ll]", wl_text)
                    if wl_match:
                        wins, losses = int(wl_match.group(1)), int(wl_match.group(2))

                map_stats.append(PlayerMapStats(
                    map=map_name,
                    wins=wins,
                    losses=losses,
                    win_rate=win_rate,
                    kd_diff=kd,
                    rating=rating,
                ))
            except Exception as e:
                logger.debug("Failed to parse map stat: %s", e)
                continue

        return map_stats

    def _parse_player_detail(self, soup: BeautifulSoup, player_id: int) -> PlayerDetailed:
        """Parse full player detail page."""
        p = PlayerDetailed(id=player_id)

        name_el = select_one(soup, ".playerName, .player-nick, .nick, h1")
        p.name = safe_text(name_el)

        rn_el = select_one(soup, ".realName, .real-name, .player-realname")
        p.real_name = safe_text(rn_el) or None

        age_el = select_one(soup, ".age, .player-age")
        age_text = safe_text(age_el)
        if age_text:
            import re
            m = re.search(r"(\d+)", age_text)
            if m:
                p.age = int(m.group(1))

        flag_el = select_one(soup, "img[class*='flag'], .country-flag img")
        if flag_el:
            alt_val = flag_el.get("alt", "")
            if isinstance(alt_val, str):
                p.country = alt_val[:2]

        photo_el = select_one(soup, "img.player-image, img[class*='player'], img[class*='photo']")
        p.photo = extract_img_url(photo_el)

        team_el = select_one(soup, ".team, .player-team, a[href*='/team/']")
        if team_el:
            team_name = safe_text(team_el)
            team_href = (team_el.get("href") if isinstance(team_el, Tag) else None)
            if not team_href and team_el.name == "a":
                team_href = extract_href(team_el)
            team_id = parse_team_id_from_url(str(team_href)) if team_href else None
            p.team = Team(id=team_id, name=team_name)

        twitter_el = select_one(soup, "a[href*='twitter.com'], a[href*='x.com']")
        if twitter_el:
            p.twitter = extract_href(twitter_el)
        twitch_el = select_one(soup, "a[href*='twitch.tv']")
        if twitch_el:
            p.twitch = extract_href(twitch_el)

        stat_elements = select_all(soup, ".stats-stat, .stat, .player-stat-box, .summary-stat")
        stats_map: dict[str, str] = {}
        for stat_el in stat_elements:
            label = safe_text(select_one(stat_el, ".label, .stat-label, .stat-name"))
            value = safe_text(select_one(stat_el, ".value, .stat-value"))
            if label and value:
                stats_map[label.lower().strip()] = value

        p.map_stats = []

        return p

    def _parse_top_players(self, soup: BeautifulSoup, period: str) -> TopPlayersResponse:
        """Parse top players listing page."""
        response = TopPlayersResponse(period=period)

        player_elements = select_all(soup, ".player-item, .stats-player-row, .player-rank-row")
        for element in player_elements:
            try:
                top = self._parse_top_player(element)
                if top:
                    response.players.append(top)
            except Exception as e:
                logger.debug("Failed to parse top player: %s", e)
                continue

        return response

    def _parse_top_player(self, element: Tag) -> TopPlayer | None:
        """Parse a single top player entry."""
        rank_el = select_one(element, ".rank, .position, .ranking-number")
        rank = safe_int(safe_text(rank_el))
        if rank is None:
            return None

        name_el = select_one(element, ".player-name, .nick, a[href*='/player/']")
        name = safe_text(name_el)
        href = extract_href(name_el) if name_el else None
        player_id = parse_player_id_from_url(href)

        team_el = select_one(element, ".team, .team-name, a[href*='/team/']")
        team_name = safe_text(team_el)
        team_href = extract_href(team_el) if team_el else None
        team_id = parse_team_id_from_url(team_href)

        rating = safe_float(safe_text(select_one(element, ".rating, .hltv-rating"))) or 0.0
        maps = safe_int(safe_text(select_one(element, ".maps, .maps-played"))) or 0
        kills = safe_int(safe_text(select_one(element, ".kills, .total-kills"))) or 0
        deaths = safe_int(safe_text(select_one(element, ".deaths, .total-deaths"))) or 0

        player_detail = PlayerDetailed(
            id=player_id,
            name=name,
            total_maps=maps,
            total_kills=kills,
            total_deaths=deaths,
            hltv_rating=rating,
        )

        return TopPlayer(
            rank=rank,
            player=player_detail,
            team=Team(id=team_id, name=team_name),
            rating=rating,
            maps_played=maps,
            kills=kills,
            deaths=deaths,
        )


__all__ = ["PlayersEndpoint"]
