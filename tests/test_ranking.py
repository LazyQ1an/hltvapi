"""
Tests for the ranking and team endpoint parsers.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.parser import select_one, select_all, safe_int, safe_text


class TestRankingParsing:
    """Test parsing ranking entries from HTML snapshots."""

    def test_ranking_entries_have_rank(self, ranking_page_html: str) -> None:
        """Ranking entries should have rank positions."""
        soup = BeautifulSoup(ranking_page_html, "html.parser")
        ranking_region = select_one(soup, ".ranking")
        assert ranking_region is not None, "No .ranking region found"

        entries = select_all(ranking_region, ".bg-holder")
        assert len(entries) > 0, "No ranking entries found"

        ranks_found = 0
        for entry in entries[:30]:
            rank_el = select_one(entry, ".position")
            if rank_el:
                rank_text = safe_text(rank_el).lstrip("#").strip()
                if safe_int(rank_text) is not None:
                    ranks_found += 1

        ratio = ranks_found / min(len(entries), 30)
        assert ratio >= 0.9, "Only {:.0f}% have ranks".format(ratio * 100)

    def test_ranking_entries_have_names(self, ranking_page_html: str) -> None:
        """Ranking entries should have team names."""
        soup = BeautifulSoup(ranking_page_html, "html.parser")
        ranking_region = select_one(soup, ".ranking")
        entries = select_all(ranking_region, ".bg-holder")

        names_found = 0
        for entry in entries[:30]:
            name_el = select_one(entry, ".teamLine .name, .name")
            if name_el and name_el.get_text(strip=True):
                names_found += 1

        ratio = names_found / min(len(entries), 30)
        assert ratio >= 0.9, "Only {:.0f}% have names".format(ratio * 100)

    def test_ranking_entries_have_points(self, ranking_page_html: str) -> None:
        """Ranking entries should have point values."""
        import re
        soup = BeautifulSoup(ranking_page_html, "html.parser")
        ranking_region = select_one(soup, ".ranking")
        entries = select_all(ranking_region, ".bg-holder")

        points_found = 0
        for entry in entries[:30]:
            points_el = select_one(entry, ".points")
            if points_el:
                text = points_el.get_text(strip=True)
                m = re.search(r"(\d+)", text)
                if m and int(m.group(1)) > 0:
                    points_found += 1

        ratio = points_found / min(len(entries), 30)
        assert ratio >= 0.9, "Only {:.0f}% have points".format(ratio * 100)


class TestTeamDetailParsing:
    """Test parsing team detail from HTML snapshots."""

    def test_team_has_roster(self, team_detail_html: str) -> None:
        """Team detail should have roster players."""
        soup = BeautifulSoup(team_detail_html, "html.parser")
        roster = select_one(soup, ".bodyshot-team.g-grid, .bodyshot-team")
        assert roster is not None, "No roster section found"

        players = select_all(roster, "a.col-custom[href*='/player/'], a[href*='/player/']")
        # A CS2 team should have 5 players (but could have subs)
        assert len(players) >= 4, "Expected >=4 players, got {}".format(len(players))
        assert len(players) <= 7, "Unusually large roster: {}".format(len(players))

    def test_team_has_ranking(self, team_detail_html: str) -> None:
        """Team detail should have ranking info."""
        soup = BeautifulSoup(team_detail_html, "html.parser")
        ranking_info = select_one(soup, ".ranking-info")
        assert ranking_info is not None, "No ranking info section"

        rank_el = select_one(ranking_info, ".value.h-rank")
        assert rank_el is not None, "No rank value found"
        rank_text = rank_el.get_text(strip=True)
        assert rank_text.startswith("#"), "Rank should be # prefixed"
