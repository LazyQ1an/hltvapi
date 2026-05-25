"""
Pydantic models for team-related data from HLTV.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .common import Player, TeamRecord
from .match import MatchOverview


class TeamRankingEntry(BaseModel):
    """A team's position in the world ranking."""

    rank: int = 0
    """Current world rank position."""
    team_id: int | None = None
    """HLTV team ID."""
    name: str = ""
    """Team name."""
    logo: str | None = None
    """Team logo URL."""
    points: int = 0
    """Ranking points."""
    change: int | None = None
    """Position change since last ranking (negative = moved up)."""
    last_place: int | None = None
    """Last week's rank position."""
    weeks_in_top30: int | None = None
    """Weeks in top 30."""
    country: str | None = None
    """Team country."""


class TeamRanking(BaseModel):
    """World ranking data for a specific date."""

    date: datetime | None = None
    """Ranking publication date."""
    teams: list[TeamRankingEntry] = Field(default_factory=list)
    """Ranked teams."""


class TeamRosterPlayer(Player):
    """Player within a team roster with additional context."""

    join_date: datetime | None = None
    """When the player joined this team."""
    is_current: bool = True
    """Whether the player is currently on the roster."""
    maps_played: int | None = None
    """Maps played with the team."""


class TeamDetail(BaseModel):
    """Full detail for a single team page."""

    id: int | None = None
    """HLTV team ID."""
    name: str = ""
    """Team name."""
    logo: str | None = None
    """Team logo URL."""
    country: str | None = None
    """Team country code."""
    region: str | None = None
    """Team region."""
    rank: int | None = None
    """Current world ranking."""
    rank_change: int | None = None
    """Rank change from last week."""
    record: TeamRecord = Field(default_factory=TeamRecord)
    """Overall record."""
    earnings: str | None = None
    """Total prize money earnings."""
    current_lineup: list[TeamRosterPlayer] = Field(default_factory=list)
    """Current active roster."""
    recent_matches: list[MatchOverview] = Field(default_factory=list)
    """Recent match results (typically last 10)."""
    upcoming_matches: list[MatchOverview] = Field(default_factory=list)
    """Upcoming matches."""
