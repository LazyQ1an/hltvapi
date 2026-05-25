"""
Pydantic models for match-related data from HLTV.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .common import Event, MapName, Player, PlayerStats, Team, TeamRecord


class MatchTeam(Team):
    """Team information within a match context."""

    score: int | None = None
    """Team's score in the match."""
    record: TeamRecord | None = None
    """Team's record in the event or recent matches."""


class MatchMap(BaseModel):
    """A map played in a match with scores and stats."""

    name: MapName = MapName.UNKNOWN
    """Map name."""
    team1_score: int = 0
    """Score for team 1."""
    team2_score: int = 0
    """Score for team 2."""
    winner_team1: bool | None = None
    """True if team1 won this map, False if team2 won, None if unknown."""
    is_halftime: bool = False
    """Whether this map is at halftime (ongoing match)."""


class PlayerMatchStats(PlayerStats):
    """Player stats within a specific match, with player identity."""

    player: Player = Field(default_factory=Player)
    """Player identity."""
    team_is_team1: bool = True
    """True if the player is on team1."""
    map_stats: dict[str, PlayerStats] | None = None
    """Per-map stats, keyed by map name."""
    is_mvp: bool = False
    """Whether this player was match MVP."""


class MatchDemo(BaseModel):
    """Downloadable demo information for a match."""

    name: str = ""
    """Demo file name."""
    url: str | None = None
    """Download URL for the demo."""
    map_name: str | None = None
    """Map this demo is for."""
    gotv: bool = True
    """Whether this is a GOTV demo."""
    source: str | None = None
    """Demo source (e.g., 'ESL', 'BLAST')."""


class MatchOverview(BaseModel):
    """Summary of a match, used in listings (upcoming / results)."""

    id: int
    """HLTV match ID."""
    team1: MatchTeam = Field(default_factory=MatchTeam)
    """First team."""
    team2: MatchTeam = Field(default_factory=MatchTeam)
    """Second team."""
    event: Event = Field(default_factory=Event)
    """Event this match belongs to."""
    date: datetime | None = None
    """Match start time."""
    format: str | None = None
    """Match format (e.g., 'bo3', 'bo5')."""
    stage: str | None = None
    """Match stage (e.g., 'Grand Final', 'Semi-final')."""
    is_live: bool = False
    """Whether the match is currently live."""
    is_upcoming: bool = False
    """Whether the match is upcoming (not started)."""
    maps: list[MapName] = Field(default_factory=list)
    """Maps vetoed/played for this match."""


class MatchDetail(MatchOverview):
    """Full detailed match information."""

    detail_maps: list[MatchMap] = Field(default_factory=list)
    """Detailed map scores with team scores and winner info."""
    """Detailed map scores."""
    players_team1: list[PlayerMatchStats] = Field(default_factory=list)
    """Team 1 player statistics."""
    players_team2: list[PlayerMatchStats] = Field(default_factory=list)
    """Team 2 player statistics."""
    demos: list[MatchDemo] = Field(default_factory=list)
    """Available demo downloads."""
    event_id: int | None = None
    """Numeric event ID."""
    vod_url: str | None = None
    """VOD/stream URL for the match."""
    has_economy_data: bool = False
    """Whether economy data is available."""
    has_live_betting: bool = False
    """Whether live betting is available."""
    winner_team1: bool | None = None
    """True if team1 won, False if team2 won, None if unknown/ongoing."""


class MatchEvent(BaseModel):
    """Detailed event reference within match context."""

    id: int | None = None
    name: str = ""
    logo: str | None = None
    prize_pool: str | None = None
    location: str | None = None
