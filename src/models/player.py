"""
Pydantic models for player-related data from HLTV.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .common import MapName, PlayerStats, Team


class PlayerAchievement(BaseModel):
    """Player achievement or award."""

    event_name: str = ""
    """Event name where achieved."""
    event_id: int | None = None
    """HLTV event ID."""
    placement: str = ""
    """Placement (e.g., '1st', '2nd', 'MVP')."""
    date: datetime | None = None
    """Date of achievement."""


class PlayerMapStats(BaseModel):
    """Player statistics for a specific map."""

    map: MapName = MapName.UNKNOWN
    """Map name."""
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    rounds_played: int = 0
    kd_diff: float = 0.0
    rating: float = 0.0


class PlayerDetailed(PlayerStats):
    """Extended player information for full profile page."""

    id: int | None = None
    """HLTV player ID."""
    name: str = ""
    """Player in-game name."""
    real_name: str | None = None
    """Real name."""
    age: int | None = None
    """Player age."""
    country: str | None = None
    """Country code."""
    photo: str | None = None
    """Profile photo URL."""
    twitter: str | None = None
    """Twitter/X handle."""
    twitch: str | None = None
    """Twitch channel URL."""
    team: Team | None = None
    """Current team."""
    signature_weapon: str | None = None
    """Most-played weapon."""
    total_kills: int = 0
    total_deaths: int = 0
    total_assists: int = 0
    total_maps: int = 0
    total_rounds: int = 0
    kd_ratio: float = 0.0
    kpr: float = 0.0
    """Kills per round."""
    dpr: float = 0.0
    """Deaths per round."""
    ap: float = 0.0
    """Assists per round."""
    impact: float = 0.0
    """HLTV impact rating."""
    adr: float = 0.0
    """Average Damage per Round."""
    kast_pct: float = 0.0
    """KAST percentage (overrides PlayerStats.kast)."""
    hltv_rating: float = 0.0
    """Overall HLTV 2.0 rating."""
    hltv_rating_vs_top5: float | None = None
    """Rating vs top 5 teams."""
    hltv_rating_vs_top10: float | None = None
    """Rating vs top 10 teams."""
    hltv_rating_vs_top20: float | None = None
    """Rating vs top 20 teams."""
    big_events_maps: int | None = None
    """Maps played at big events."""
    big_events_rating: float | None = None
    """Rating at big events."""
    map_stats: list[PlayerMapStats] = Field(default_factory=list)
    """Per-map performance."""



class TopPlayer(BaseModel):
    """A player entry in top player lists (rankings)."""

    rank: int = 0
    """Position in ranking."""
    player: PlayerDetailed | None = None
    """Player information."""
    team: Team | None = None
    """Current team."""
    rating: float = 0.0
    """Rating for the selected period."""
    maps_played: int = 0
    """Maps played during period."""
    kills: int = 0
    """Total kills."""
    deaths: int = 0
    """Total deaths."""


class TopPlayersResponse(BaseModel):
    """Response model for top player listings."""

    players: list[TopPlayer] = Field(default_factory=list)
    period: str = ""
    """Period description (e.g., 'Last 3 Months')."""
    start_date: datetime | None = None
    end_date: datetime | None = None
