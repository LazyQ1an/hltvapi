"""
Match-related endpoints: upcoming matches, live matches, match detail.
"""
from __future__ import annotations
import re
from bs4 import BeautifulSoup, Tag
from src.client import HLTVClient
from src.models.match import (
    MatchOverview, MatchDetail, MatchMap, MatchTeam,
    PlayerMatchStats, MatchDemo,
)
from src.models.common import Event, MapName, Player
from src.parser import (
    safe_text, safe_int, safe_float, extract_href, extract_img_url,
    make_absolute_url, parse_date_string, parse_match_id_from_url,
    parse_team_id_from_url, parse_player_id_from_url,
    select_one, select_all, parse_event_id_from_url,
)
from src.utils.logger import get_logger
from src.utils.parsestats import get_parse_stats

logger = get_logger("endpoints.matches")


def _make_event(event_id: int | None, name: str, logo: str | None) -> Event:
    """Create an Event model from scraped fields.

    Args:
        event_id: HLTV event ID.
        name: Event name.
        logo: Event logo URL.

    Returns:
        Event model instance.
    """
    return Event(id=event_id, name=name, logo=logo)


class MatchesEndpoint:
    """Endpoints for match-related data."""

    BASE_URL = "https://www.hltv.org"

    def __init__(self, client: HLTVClient) -> None:
        self._client = client
        self._parse_stats = get_parse_stats("matches.upcoming")

    async def get_upcoming(self) -> list[MatchOverview]:
        """Fetch all upcoming matches from the matches page.

        Returns:
            List of MatchOverview for upcoming/live matches.
        """
        url = f"{self.BASE_URL}/matches"
        soup = await self._client.get_soup(url)
        matches: list[MatchOverview] = []

        # HLTV matches page structure:
        match_wrappers = select_all(soup, ".match-wrapper")

        for wrapper in match_wrappers:
            try:
                match = self._parse_match_overview(wrapper)
                if match and match.id:
                    is_live = bool(select_one(wrapper, ".match-meta-live"))
                    match.is_live = is_live
                    match.is_upcoming = not is_live
                    matches.append(match)
                    self._parse_stats.record(success=True)
                else:
                    self._parse_stats.record(success=False)
            except Exception:
                self._parse_stats.record(success=False)

        self._parse_stats.report()
        return matches

    async def get_results(
        self,
        page: int = 1,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[MatchOverview]:
        """Fetch historical match results with pagination.

        Args:
            page: Page number (1-indexed).
            start_date: Filter from date (YYYY-MM-DD).
            end_date: Filter to date (YYYY-MM-DD).

        Returns:
            List of MatchOverview for completed matches.
        """
        params = f"?offset={max(0, (page - 1) * 100)}"
        
        # Not using start_date/end_date in query since HLTV uses a date range approach
        url = f"{self.BASE_URL}/results{params}"
        
        # If date filtering needed, use HLTV's date search
        if start_date and end_date:
            url += f"&startDate={start_date}&endDate={end_date}"
        
        soup = await self._client.get_soup(url)
        matches: list[MatchOverview] = []
        
        # HLTV results page uses .result-con elements
        result_elements = select_all(soup, ".result-con")
        
        for element in result_elements:
            try:
                match = self._parse_result_overview(element)
                if match and match.id:
                    matches.append(match)
            except Exception as e:
                logger.debug("Failed to parse result: %s", e)
                continue
                
        return matches

    async def get_detail(self, match_id: int) -> MatchDetail:
        """Fetch full details for a specific match by its ID.

        Args:
            match_id: HLTV match ID.

        Returns:
            MatchDetail with full information.
        """
        url = f"{self.BASE_URL}/matches/{match_id}/-"
        soup = await self._client.get_soup(url)
        return self._parse_match_detail(soup, match_id)

    # ── Private parsing helpers ────────────────────────────────────

    def _parse_match_overview(self, element: Tag) -> MatchOverview | None:
        """Parse a match overview from the match-wrapper structure.

        HLTV matches page structure:
        <div class="match-wrapper" data-match-id="123" team1="456" team2="789">
          <div class="match"> <div class="match">
            <a class="match-top">
              <div class="match-event text-ellipsis">
                <img class="match-event-logo" src="...">
                <div class="text-ellipsis">Event Name</div>
                <div class="match-stage">Semifinal</div>
              </div>
            </a>
            <div class="match-bottom">
              <a class="match-info">
                <div class="match-meta match-meta-live">Live</div>
                <div class="match-meta">bo3</div>
              </a>
              <a class="match-teams">
                <div class="match-team">
                  <img class="match-team-logo" src="...">
                  <div class="match-teamname">Team1</div>
                </div>
                <div class="match-team">
                  <img class="match-team-logo" src="...">
                  <div class="match-teamname">Team2</div>
                </div>
              </a>
            </div>
          </div> </div>
        </div>
        """
        # Get match ID from data attribute
        match_id = safe_int(str(element.get("data-match-id", "")))
        if not match_id:
            return None
        
        # Team names from .match-teamname elements within .match-teams
        team_els = select_all(element, ".match-teamname")
        team1_name = safe_text(team_els[0]) if len(team_els) > 0 else ""
        team2_name = safe_text(team_els[1]) if len(team_els) > 1 else ""
        
        # Team logos
        logo_els = select_all(element, ".match-team-logo")
        team1_logo = extract_img_url(logo_els[0]) if len(logo_els) > 0 else None
        team2_logo = extract_img_url(logo_els[1]) if len(logo_els) > 1 else None
        
        # Team IDs from data attributes
        team1_id = safe_int(str(element.get("team1", "")))
        team2_id = safe_int(str(element.get("team2", "")))
        
        team1 = MatchTeam(id=team1_id, name=team1_name, logo=team1_logo)
        team2 = MatchTeam(id=team2_id, name=team2_name, logo=team2_logo)
        
        # Event name from .match-event > .text-ellipsis (the inner one)
        event_name_el = select_one(element, ".match-event .text-ellipsis")
        event_name = safe_text(event_name_el)
        
        # Event logo
        event_logo_el = select_one(element, ".match-event-logo")
        event_logo = extract_img_url(event_logo_el)
        
        # Event ID from data attribute
        event_id = safe_int(str(element.get("data-event-id", "")))
        
        # Stage
        stage_el = select_one(element, ".match-stage")
        stage = safe_text(stage_el) or None
        
        # Format (bo3, bo5) from .match-meta (not .match-meta-live)
        all_matches = self._parse_format(element)
        
        return MatchOverview(
            id=match_id,
            team1=team1,
            team2=team2,
            event=_make_event(event_id, event_name, event_logo),
            format=all_matches,
            stage=stage,
            is_live=bool(select_one(element, ".match-meta-live")),
        )

    def _parse_format(self, element: Tag) -> str | None:
        """Extract match format (bo3, bo5) from a match element."""
        meta_els = select_all(element, ".match-meta")
        for meta in meta_els:
            text = safe_text(meta)
            if text.lower().startswith("bo"):
                return text
        return None

    def _parse_result_overview(self, element: Tag) -> MatchOverview | None:
        """Parse a match overview from the result-con structure.

        HLTV results page structure:
        <div class="result-con">
          <a href="/matches/...">
            <div class="result">
              <table><tr>
                <td class="team-cell">
                  <div class="line-align team1">
                    <div class="team">Team1</div>
                    <img class="team-logo" src="...">
                  </div>
                </td>
                <td class="result-score">
                  <span class="score-lost">0</span> - <span class="score-won">2</span>
                </td>
                <td class="team-cell">
                  <div class="line-align team2">
                    <img class="team-logo" src="...">
                    <div class="team team-won">Team2</div>
                  </div>
                </td>
                <td class="event">
                  <img class="event-logo" src="...">
                  <span class="event-name">Event Name</span>
                </td>
                <td class="star-cell">
                  <div class="map-and-stars">
                    <div class="stars">...</div>
                    <div class="map map-text">bo3</div>
                  </div>
                </td>
              </tr></table>
            </div>
          </a>
        </div>
        """
        link = select_one(element, "a[href*='/matches/']")
        if not link:
            return None
        href = extract_href(link)
        match_id = parse_match_id_from_url(href)
        if not match_id:
            return None

        # Team 1
        team1_cell = select_one(element, ".line-align.team1")
        team1_name = safe_text(select_one(team1_cell, ".team"))
        team1_logo = extract_img_url(select_one(team1_cell, "img"))
        team1_link = select_one(team1_cell, "a[href*='/team/']")
        team1_id = parse_team_id_from_url(extract_href(team1_link)) if team1_link else None

        # Team 2
        team2_cell = select_one(element, ".line-align.team2")
        team2_name = safe_text(select_one(team2_cell, ".team"))
        team2_logo = extract_img_url(select_one(team2_cell, "img"))
        team2_link = select_one(team2_cell, "a[href*='/team/']")
        team2_id = parse_team_id_from_url(extract_href(team2_link)) if team2_link else None

        # Score: .result-score contains two <span> elements
        # First span is team1's score, second span is team2's score
        # They may be .score-lost or .score-won depending on who won
        t1_score = 0
        t2_score = 0
        team1_score_el = select_one(element, ".result-score")
        if team1_score_el:
            score_spans = select_all(team1_score_el, "span")
            if len(score_spans) >= 1:
                t1_score = safe_int(safe_text(score_spans[0])) or 0
            if len(score_spans) >= 2:
                t2_score = safe_int(safe_text(score_spans[1])) or 0

        # Event
        event_name = safe_text(select_one(element, ".event-name"))
        event_logo = extract_img_url(select_one(element, ".event-logo"))
        event_id_tag = select_one(element, "[data-event-id]")
        event_id = safe_int(str(event_id_tag.get("data-event-id"))) if event_id_tag is not None else None

        # Format
        format_text = safe_text(select_one(element, ".map-text")) or None

        return MatchOverview(
            id=match_id,
            team1=MatchTeam(id=team1_id, name=team1_name, logo=team1_logo, score=t1_score),
            team2=MatchTeam(id=team2_id, name=team2_name, logo=team2_logo, score=t2_score),
            event=_make_event(event_id, event_name, event_logo),
            format=format_text,
        )

    def _parse_match_detail(self, soup: BeautifulSoup, match_id: int) -> MatchDetail:
        """Parse full match detail page from HLTV match page."""
        overview = MatchDetail(id=match_id)

        # 1. Team info from teamsBox
        # HLTV structure:
        # <div class="standard-box teamsBox">
        #   <div class="team">
        #     <div class="team1-gradient"><a href="/team/12468/"><div class="teamName">Legacy</div></a></div>
        #   </div>
        #   <div class="team">
        #     <div class="team2-gradient"><a href="/team/9928/"><div class="teamName">GamerLegion</div></a></div>
        #   </div>
        # </div>
        try:
            teams_box = select_one(soup, ".teamsBox")
            if teams_box:
                team_divs = select_all(teams_box, ".team")
                # Team 1
                if len(team_divs) > 0:
                    name_el = select_one(team_divs[0], ".teamName")
                    overview.team1.name = safe_text(name_el)
                    link_el = select_one(team_divs[0], "a[href*='/team/']")
                    overview.team1.id = parse_team_id_from_url(extract_href(link_el))
                    logo_el = select_one(team_divs[0], "img.logo")
                    overview.team1.logo = extract_img_url(logo_el)
                # Team 2
                if len(team_divs) > 1:
                    name_el = select_one(team_divs[1], ".teamName")
                    overview.team2.name = safe_text(name_el)
                    link_el = select_one(team_divs[1], "a[href*='/team/']")
                    overview.team2.id = parse_team_id_from_url(extract_href(link_el))
                    logo_el = select_one(team_divs[1], "img.logo")
                    overview.team2.logo = extract_img_url(logo_el)

                # Scores from the team area (for completed matches)
                score_els = select_all(teams_box, "[class*='score']")
                score_vals = [safe_int(safe_text(se)) for se in score_els]
                score_vals = [v for v in score_vals if v is not None]
                if len(score_vals) >= 2:
                    overview.team1.score = score_vals[0]
                    overview.team2.score = score_vals[1]
        except Exception as e:
            logger.debug("Failed to parse team info: %s", e)

        # 2. Event info from teamsBox event section
        try:
            event_link = select_one(soup, ".teamsBox .event a, .event a[href*='/events/']")
            if event_link:
                overview.event.name = safe_text(event_link)
                overview.event.id = parse_event_id_from_url(extract_href(event_link))
            else:
                event_el = select_one(soup, ".event, .matchEvent, .tournament")
                if event_el:
                    overview.event.name = safe_text(event_el)
                    ev_link = select_one(event_el, "a")
                    overview.event.id = parse_event_id_from_url(extract_href(ev_link)) if ev_link else None
                    overview.event.logo = extract_img_url(select_one(event_el, "img"))
        except Exception as e:
            logger.debug("Failed to parse event: %s", e)

        # 3. Date
        try:
            date_el = select_one(soup, ".date, .matchDate, .time[datetime]")
            if date_el:
                date_str = date_el.get("datetime") or safe_text(date_el)
                overview.date = parse_date_string(str(date_str))
        except Exception as e:
            logger.debug("Failed to parse date: %s", e)

        # 4. Maps from .mapholder
        try:
            map_holders = select_all(soup, ".mapholder")
            for mh in map_holders:
                try:
                    map_name = MapName.UNKNOWN
                    map_name_el = select_one(mh, ".mapname")
                    map_name_text = safe_text(map_name_el)
                    for m in MapName:
                        if m.value.lower() in map_name_text.lower():
                            map_name = m
                            break

                    t1_score = 0
                    t2_score = 0
                    results_el = select_one(mh, ".results")
                    if results_el:
                        nums = re.findall(r'\d+', safe_text(results_el))
                        if len(nums) >= 2:
                            t1_score = int(nums[0])
                            t2_score = int(nums[1])

                    overview.detail_maps.append(MatchMap(
                        name=map_name,
                        team1_score=t1_score,
                        team2_score=t2_score,
                        winner_team1=bool(t1_score > t2_score) if t1_score != t2_score else None,
                    ))
                except Exception as e:
                    logger.debug("Failed to parse map holder: %s", e)
        except Exception as e:
            logger.debug("Failed to parse maps section: %s", e)

        # 5. Player stats
        try:
            all_players = self._parse_all_player_stats(soup)
            if len(all_players) > 0:
                overview.players_team1 = all_players[:5]
            if len(all_players) > 5:
                overview.players_team2 = all_players[5:10]
        except Exception as e:
            logger.debug("Failed to parse player stats: %s", e)

        # 6. Demos
        try:
            demo_links = select_all(soup, "a[href*='download'], a[href*='demo']")
            for demo in demo_links:
                try:
                    overview.demos.append(MatchDemo(
                        name=safe_text(demo) or "demo",
                        url=make_absolute_url(extract_href(demo)),
                    ))
                except Exception as e:
                    logger.debug("Failed to parse demo link: %s", e)
        except Exception as e:
            logger.debug("Failed to parse demos section: %s", e)

        # 7. Winner from map scores
        if len(overview.detail_maps) > 0:
            t1_wins = sum(1 for m in overview.detail_maps if m.winner_team1 is True)
            t2_wins = sum(1 for m in overview.detail_maps if m.winner_team1 is False)
            if t1_wins > t2_wins:
                overview.winner_team1 = True
            elif t2_wins > t1_wins:
                overview.winner_team1 = False

        # 8. Live indicator
        try:
            overview.is_live = bool(select_one(soup, ".live, .matchLive, .live-pill, [class*='live']"))
        except Exception as e:
            logger.debug("Failed to check live status: %s", e)

        return overview

    def _parse_all_player_stats(self, soup: BeautifulSoup) -> list[PlayerMatchStats]:
        """Parse all player statistics from the match detail stats table.

        Returns players in page order (team1 then team2).
        """
        players: list[PlayerMatchStats] = []

        try:
            stat_table = (
                select_one(soup, ".lineups-compare-middle-table")
                or select_one(soup, "table.totalstats")
                or select_one(soup, ".stats-content table")
            )
            if not stat_table:
                return players

            rows = select_all(stat_table, "tr")
            player_rows = [r for r in rows if select_one(r, "a[href*='/player/']")]

            for row in player_rows:
                try:
                    name_el = select_one(row, "a[href*='/player/']")
                    name = safe_text(name_el)
                    player_id = parse_player_id_from_url(extract_href(name_el))

                    cells = select_all(row, "td")
                    data_cells = cells[1:] if cells else []

                    numbers: list[float] = []
                    for cell in data_cells:
                        val = safe_float(safe_text(cell))
                        if val is not None:
                            numbers.append(val)

                    kills = int(numbers[0]) if len(numbers) > 0 else 0
                    deaths = int(numbers[1]) if len(numbers) > 1 else 0
                    assists = int(numbers[2]) if len(numbers) > 2 else 0
                    adr = numbers[3] if len(numbers) > 3 else 0.0
                    rating = numbers[4] if len(numbers) > 4 else 0.0

                    players.append(PlayerMatchStats(
                        player=Player(id=player_id, name=name),
                        kills=kills,
                        deaths=deaths,
                        assists=assists,
                        kd_diff=kills - deaths,
                        adr=adr,
                        rating=rating,
                    ))
                except Exception as e:
                    logger.debug("Failed to parse player row: %s", e)
                    continue
        except Exception as e:
            logger.debug("Failed to find player stats table: %s", e)

        return players


__all__ = ["MatchesEndpoint"]
