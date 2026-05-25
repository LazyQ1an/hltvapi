"""
Tests for the matches endpoint parser.

Uses HTML snapshots instead of live HTTP calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.endpoints.matches import MatchesEndpoint
from src.models.match import MatchOverview, MatchDetail


class TestMatchOverviewParsing:
    """Test parsing upcoming matches from HTML snapshots."""

    def test_parse_upcoming_match_names(self, matches_page_html: str) -> None:
        """Upcoming matches should contain team names."""
        soup = BeautifulSoup(matches_page_html, "html.parser")
        # Use the same logic as the endpoint
        from src.parser import select_one, select_all

        wrappers = select_all(soup, ".match-wrapper")
        assert len(wrappers) > 0, "No match wrappers found in fixture"

        # Check a few have team names
        teams_found = 0
        for wrapper in wrappers[:10]:
            team_els = select_all(wrapper, ".match-teamname")
            if len(team_els) >= 2:
                t1 = team_els[0].get_text(strip=True)
                t2 = team_els[1].get_text(strip=True)
                if t1 and t2:
                    teams_found += 1

        # At least 80% should have team names
        ratio = teams_found / min(len(wrappers), 10)
        assert ratio >= 0.8, "Only {:.0f}% of matches have team names".format(ratio * 100)

    def test_parse_match_ids(self, matches_page_html: str) -> None:
        """Match wrappers should have data-match-id attributes."""
        from src.parser import select_all, safe_int

        wrappers = select_all(BeautifulSoup(matches_page_html, "html.parser"), ".match-wrapper")
        ids_found = sum(
            1 for w in wrappers
            if safe_int(str(w.get("data-match-id", ""))) is not None
        )
        ratio = ids_found / len(wrappers)
        assert ratio >= 0.9, "Only {:.0f}% have match IDs".format(ratio * 100)

    def test_parse_event_names(self, matches_page_html: str) -> None:
        """Match events should have event names."""
        soup = BeautifulSoup(matches_page_html, "html.parser")
        from src.parser import select_one, select_all

        wrappers = select_all(soup, ".match-wrapper")
        events_found = 0
        for wrapper in wrappers[:10]:
            event_text = select_one(wrapper, ".match-event .text-ellipsis")
            if event_text and event_text.get_text(strip=True):
                events_found += 1

        ratio = events_found / min(len(wrappers), 10)
        assert ratio >= 0.8, "Only {:.0f}% have event names".format(ratio * 100)


class TestResultsParsing:
    """Test parsing results from HTML snapshots."""

    def test_parse_result_scores(self, results_page_html: str) -> None:
        """Result entries should have scores."""
        from src.parser import select_one, select_all, safe_int

        soup = BeautifulSoup(results_page_html, "html.parser")
        results = select_all(soup, ".result-con")
        assert len(results) > 0, "No results found"

        scores_found = 0
        for result in results[:20]:
            score_el = select_one(result, ".result-score")
            if score_el:
                spans = select_all(score_el, "span")
                scores = [safe_int(s.get_text(strip=True)) for s in spans if safe_int(s.get_text(strip=True)) is not None]
                if len(scores) >= 2:
                    scores_found += 1

        ratio = scores_found / min(len(results), 20)
        assert ratio >= 0.8, "Only {:.0f}% have scores".format(ratio * 100)

    def test_parse_result_team_names(self, results_page_html: str) -> None:
        """Result entries should have team names."""
        from src.parser import select_one, select_all

        soup = BeautifulSoup(results_page_html, "html.parser")
        results = select_all(soup, ".result-con")

        teams_found = 0
        for result in results[:20]:
            t1 = select_one(result, ".line-align.team1 .team")
            t2 = select_one(result, ".line-align.team2 .team")
            if t1 and t2 and t1.get_text(strip=True) and t2.get_text(strip=True):
                teams_found += 1

        ratio = teams_found / min(len(results), 20)
        assert ratio >= 0.8, "Only {:.0f}% have team names".format(ratio * 100)


class TestMatchDetailParsing:
    """Test parsing match detail from HTML snapshots."""

    def test_parse_team_names(self, match_detail_html: str) -> None:
        """Match detail should have both team names."""
        from src.parser import select_one, select_all

        soup = BeautifulSoup(match_detail_html, "html.parser")
        teams_box = select_one(soup, ".teamsBox")
        assert teams_box is not None, "No teamsBox found"

        team_divs = select_all(teams_box, ".team")
        assert len(team_divs) >= 2, "Less than 2 team divs"

        names = []
        for td in team_divs[:2]:
            name_el = select_one(td, ".teamName")
            names.append(name_el.get_text(strip=True) if name_el else "")

        assert names[0], "Team1 name is empty"
        assert names[1], "Team2 name is empty"
        assert names[0] != names[1], "Team names are identical"

    def test_parse_event(self, match_detail_html: str) -> None:
        """Match detail should have an event name."""
        from src.parser import select_one

        soup = BeautifulSoup(match_detail_html, "html.parser")
        event_link = select_one(soup, ".teamsBox .event a, a[href*='/events/']")
        assert event_link is not None, "No event link found"
        assert event_link.get_text(strip=True), "Event name is empty"

    def test_parse_maps(self, match_detail_html: str) -> None:
        """Match detail should have maps section."""
        from src.parser import select_all

        soup = BeautifulSoup(match_detail_html, "html.parser")
        map_holders = select_all(soup, ".mapholder")
        assert len(map_holders) > 0, "No mapholders found"
