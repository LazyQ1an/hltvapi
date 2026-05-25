"""
Team-related endpoints: world ranking, team detail, roster, recent matches.
"""
from __future__ import annotations
from bs4 import BeautifulSoup, Tag
from src.client import HLTVClient
from src.models.team import (
    TeamRanking, TeamRankingEntry, TeamDetail, TeamRosterPlayer,
)
from src.models.match import MatchOverview
from src.models.common import TeamRecord
from src.parser import (
    safe_text, safe_int, extract_href, extract_img_url,
    parse_date_string, parse_team_id_from_url,
    parse_player_id_from_url, select_one, select_all,
)
from src.utils.logger import get_logger

logger = get_logger("endpoints.teams")

class TeamsEndpoint:
    """Endpoints for team-related data."""

    BASE_URL = "https://www.hltv.org"

    def __init__(self, client: HLTVClient) -> None:
        self._client = client

    async def get_ranking(self) -> TeamRanking:
        """Fetch the current world team ranking.

        Returns:
            TeamRanking with ranked teams.
        """
        url = f"{self.BASE_URL}/ranking/teams"
        soup = await self._client.get_soup(url)
        ranking = TeamRanking()

        # HLTV ranking structure:
        # <div class='ranking'> (the main ranking container)
        #   <div class='bg-holder'>
        #     <div class='ranking-header'>
        #       <span class='position'>#1</span>
        #       <span class='team-logo'><img ...></span>
        #       <div class='teamLine'><span class='name'>TeamName</span><span class='points'>...</span></div>
        #       <div class='change'>-</div>
        #     </div>
        #   </div>
        # </div>
        
        ranking_region = select_one(soup, ".ranking")
        if ranking_region:
            rank_elements = select_all(ranking_region, ".bg-holder")
        else:
            rank_elements = select_all(soup, ".bg-holder")

        for element in rank_elements:
            try:
                entry = self._parse_ranking_entry(element)
                if entry:
                    ranking.teams.append(entry)
            except Exception as e:
                logger.debug("Failed to parse ranking entry: %s", e)
                continue

        # Date from ranking header
        date_el = select_one(soup, ".ranking-date, .date, time[datetime]")
        if date_el:
            date_str = date_el.get("datetime", safe_text(date_el))
            ranking.date = parse_date_string(str(date_str))

        return ranking

    async def get_detail(self, team_id: int) -> TeamDetail:
        """Fetch full team details including roster and recent matches.

        Args:
            team_id: HLTV team ID.

        Returns:
            TeamDetail with full information.
        """
        url = f"{self.BASE_URL}/team/{team_id}/-"
        soup = await self._client.get_soup(url)
        return self._parse_team_detail(soup, team_id)

    async def get_roster(self, team_id: int) -> list[TeamRosterPlayer]:
        """Fetch the current roster of a team.

        Args:
            team_id: HLTV team ID.

        Returns:
            List of current roster players.
        """
        detail = await self.get_detail(team_id)
        return detail.current_lineup

    async def get_recent_matches(self, team_id: int) -> list[MatchOverview]:
        """Fetch recent matches for a team.

        Args:
            team_id: HLTV team ID.

        Returns:
            List of recent match overviews.
        """
        detail = await self.get_detail(team_id)
        return detail.recent_matches

    def _parse_ranking_entry(self, element: Tag) -> TeamRankingEntry | None:
        """Parse a single team ranking entry.

        HLTV ranking entry structure:
        <div class="bg-holder">
          <div class="ranking-header">
            <span class="position wide-position">#1</span>
            <span class="team-logo"><img alt="TeamName" src="..."></span>
            <div class="relative">
              <div class="teamLine">
                <span class="name">TeamName</span>
                <span class="points">(1000 HLTV points)</span>
              </div>
            </div>
            <span class="filler"></span>
            <div class="change neutral">-</div>
          </div>
          ...
        </div>
        """
        rank_el = select_one(element, ".position")
        rank_text = safe_text(rank_el).lstrip("#").strip()
        rank = safe_int(rank_text)
        if rank is None:
            return None

        name_el = select_one(element, ".teamLine .name, .name")
        name = safe_text(name_el)

        # Team link is in .more a[href*='/team/'] or .lineup-con a[href*='/team/']
        team_link = select_one(element, "a[href*='/team/']")
        team_id = parse_team_id_from_url(extract_href(team_link)) if team_link else None

        logo_el = select_one(element, ".team-logo img, img.team-logo, .ranking-header img")
        logo = extract_img_url(logo_el)

        # Points from .points - extract number from "(1000 points)"
        points_el = select_one(element, ".points")
        points_text = safe_text(points_el)
        import re as _re
        points_match = _re.search(r"(\d+)", points_text)
        points = int(points_match.group(1)) if points_match else 0

        # Change from .change element
        change_el = select_one(element, ".change")
        change_text = safe_text(change_el).strip()
        if change_text and change_text != "-":
            change = safe_int(change_text.replace("+", ""))
        else:
            change = 0

        return TeamRankingEntry(
            rank=rank,
            team_id=team_id,
            name=name,
            logo=logo,
            points=points,
            change=change,
        )

    def _parse_team_detail(self, soup: BeautifulSoup, team_id: int) -> TeamDetail:
        """Parse full team detail page.

        HLTV team detail structure:
        - Team name in <h1> or .profile-team-name
        - Ranking info in .ranking-info > .value.h-rank (text: "#1")
        - Roster in .bodyshot-team.g-grid > a.col-custom[href*='/player/']
          Each player: img.bodyshot-team-img (photo), .text-ellipsis.bold (nickname),
          img.flag (country flag)
        - Recent matches: scattered a[href*='/matches/'] with text "Match"
        """
        detail = TeamDetail(id=team_id)

        # Team name
        name_el = select_one(soup, "h1, .profile-team-name, .team-name")
        detail.name = safe_text(name_el)

        # Logo
        logo_el = select_one(soup, "img.team-logo, img[class*='logo']")
        detail.logo = extract_img_url(logo_el)

        # Country flag from team header
        flag_el = select_one(soup, "img.flag, img[class*='flag']")
        if flag_el:
            alt_val = flag_el.get("alt", "")
            if isinstance(alt_val, str) and alt_val:
                detail.country = alt_val[:2]

        # Region
        region_el = select_one(soup, ".region, .team-region")
        detail.region = safe_text(region_el) or None

        # Rank from .ranking-info section
        rank_value_el = select_one(soup, ".ranking-info .value.h-rank")
        if rank_value_el:
            rank_text = safe_text(rank_value_el).lstrip("#").strip()
            detail.rank = safe_int(rank_text)

        # Record from profile stats section
        record_text = safe_text(select_one(soup, ".record, .win-loss, .team-record, [class*='record']"))
        if record_text:
            import re
            wins = losses = 0
            m = re.search(r"(\d+)\s*[Ww]\s*/\s*(\d+)\s*[Ll]", record_text)
            if m:
                wins, losses = int(m.group(1)), int(m.group(2))
            detail.record = TeamRecord(wins=wins, losses=losses)

        # Earnings
        earnings_el = select_one(soup, ".earnings, .prize-money, .total-earnings, [class*='earnings']")
        detail.earnings = safe_text(earnings_el) or None

        # Roster from .bodyshot-team grid
        roster_container = select_one(soup, ".bodyshot-team.g-grid, .bodyshot-team")
        if roster_container:
            player_links = select_all(roster_container, "a.col-custom[href*='/player/'], a[href*='/player/']")
        else:
            player_links = select_all(soup, "a.col-custom[href*='/player/']")

        for player_el in player_links:
            try:
                player = self._parse_roster_player_v2(player_el)
                if player and player.name:
                    detail.current_lineup.append(player)
            except Exception as e:
                logger.debug("Failed to parse roster player: %s", e)
                continue

        # Recent matches — find match links in the main content area
        match_links = select_all(soup, "a[href*='/matches/']")
        seen_match_ids: set[int] = set()
        for link in match_links:
            href = extract_href(link)
            match_id = None
            if href:
                import re
                m = re.search(r"/matches/(\d+)/", href)
                if m:
                    match_id = int(m.group(1))
            if match_id and match_id not in seen_match_ids:
                seen_match_ids.add(match_id)
                try:
                    from src.models.match import MatchOverview, MatchTeam
                    match = MatchOverview(
                        id=match_id,
                        team1=MatchTeam(name=detail.name),
                    )
                    detail.recent_matches.append(match)
                except Exception as e:
                    logger.debug("Failed to create match ref: %s", e)
                    continue

        return detail

    def _parse_roster_player_v2(self, element: Tag) -> TeamRosterPlayer | None:
        """Parse a roster player from the bodyshot-team grid.

        Structure:
        <a class="col-custom" href="/player/7322/apex" title="apEX">
          <div class="overlayImageFrame">
            <img class="bodyshot-team-img" src="...">
            <div class="text-ellipsis nickname-container">
              <div class="playerFlagName">
                <span><img class="flag" src="/img/static/flags/30x20/FR.gif" alt="France"></span>
                <span class="text-ellipsis bold">apEX</span>
              </div>
            </div>
          </div>
        </a>
        """
        href = extract_href(element)
        player_id = parse_player_id_from_url(href)
        if not player_id:
            return None

        # Nickname from .text-ellipsis.bold
        name_el = select_one(element, ".text-ellipsis.bold, .bold, [class*='nickname'] span.bold")
        name = safe_text(name_el)

        # Photo
        photo_el = select_one(element, "img.bodyshot-team-img, img[class*='bodyshot']")
        photo = extract_img_url(photo_el)

        # Country from flag img alt
        flag_el = select_one(element, "img.flag")
        country = None
        if flag_el:
            alt_val = flag_el.get("alt", "")
            if isinstance(alt_val, str):
                country = alt_val[:2]

        return TeamRosterPlayer(
            id=player_id,
            name=name,
            photo=photo,
            country=country,
            is_current=True,
        )

    def _parse_roster_player(self, element: Tag) -> TeamRosterPlayer | None:
        """Parse a roster player element."""
        link = select_one(element, "a[href*='/player/']")
        if not link:
            return None

        name = safe_text(link)
        href = extract_href(link)
        player_id = parse_player_id_from_url(href)

        photo = extract_img_url(select_one(element, "img"))

        country_el = select_one(element, "img[class*='flag'], .country")
        country = None
        if country_el:
            alt_val = country_el.get("alt", "")
            if isinstance(alt_val, str):
                country = alt_val[:2]

        maps_played = None
        maps_el = select_one(element, ".played-maps, .maps-played, .maps-count")
        if maps_el:
            maps_played = safe_int(safe_text(maps_el))

        return TeamRosterPlayer(
            id=player_id,
            name=name,
            photo=photo,
            country=country or None,
            is_current=True,
            maps_played=maps_played,
        )

    def _parse_recent_match(self, element: Tag) -> MatchOverview | None:
        """Parse a recent match element from team page."""
        from src.models.match import MatchOverview, MatchTeam
        from src.models.common import Event

        link = element if element.name == "a" else select_one(element, "a[href*='/matches/']")
        if not link:
            return None

        href = extract_href(link)
        match_id = None
        if href:
            import re
            m = re.search(r"/matches/(\d+)/", href)
            if m:
                match_id = int(m.group(1))

        if not match_id:
            return None

        team_elements = select_all(element, ".team-cell, .team, .team-name")
        teams = []
        for t in team_elements:
            name = safe_text(t)
            score_el = select_one(t, ".score")
            score = safe_int(safe_text(score_el))
            t_link = select_one(t, "a[href*='/team/']")
            tid = None
            if t_link:
                import re
                m = re.search(r"/team/(\d+)/", extract_href(t_link) or "")
                if m:
                    tid = int(m.group(1))
            teams.append(MatchTeam(id=tid, name=name, score=score))

        event_el = select_one(element, ".event, .tournament")
        event_name = safe_text(event_el)

        return MatchOverview(
            id=match_id,
            team1=teams[0] if len(teams) > 0 else MatchTeam(),
            team2=teams[1] if len(teams) > 1 else MatchTeam(),
            event=Event(name=event_name),
        )


__all__ = ["TeamsEndpoint"]
