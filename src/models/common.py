"""
Shared Pydantic models used across multiple HLTV scraper endpoints.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MapName(str, Enum):
    """Counter-Strike 2 map names."""

    ANCIENT = "Ancient"
    ANUBIS = "Anubis"
    DUST2 = "Dust2"
    INFERNO = "Inferno"
    MIRAGE = "Mirage"
    NUKE = "Nuke"
    OVERPASS = "Overpass"
    TRAIN = "Train"
    VERTIGO = "Vertigo"
    OFFICE = "Office"
    UNKNOWN = "Unknown"


class Team(BaseModel):
    """Basic team information (used in listings and references)."""

    id: int | None = None
    """HLTV team ID."""
    name: str = ""
    """Team name."""
    logo: str | None = None
    """Team logo URL."""


class Player(BaseModel):
    """Basic player information (used in listings and references)."""

    id: int | None = None
    """HLTV player ID."""
    name: str = ""
    """Player in-game name (IGN)."""
    real_name: str | None = None
    """Player real name (if available)."""
    photo: str | None = None
    """Player photo URL."""
    country: str | None = None
    """Player country code (e.g., 'DK')."""


class Event(BaseModel):
    """Basic event/tournament information (used in references)."""

    id: int | None = None
    """HLTV event ID."""
    name: str = ""
    """Event name."""
    logo: str | None = None
    """Event logo URL."""


class MapScore(BaseModel):
    """Scoreline for a single map."""

    map: MapName = MapName.UNKNOWN
    """Map name."""
    team1_score: int = 0
    """Score for team 1 / CT side."""
    team2_score: int = 0
    """Score for team 2 / T side."""


class PlayerStats(BaseModel):
    """Per-player match statistics."""

    kills: int = 0
    deaths: int = 0
    assists: int = 0
    kd_diff: int = 0
    adr: float = 0.0
    """Average Damage per Round."""
    kast: float | None = 0.0
    """KAST percentage (0-100)."""
    rating: float = 0.0
    """HLTV rating."""
    headshots: int = 0
    hs_percentage: float = 0.0
    """Headshot percentage (0-100)."""


class TeamRecord(BaseModel):
    """Team win/loss record."""

    wins: int = 0
    losses: int = 0
    draws: int = 0
    total_maps: int = 0

    @property
    def win_rate(self) -> float:
        """Calculate win rate as percentage."""
        if self.total_maps == 0:
            return 0.0
        return round((self.wins / self.total_maps) * 100, 2)


class PageInfo(BaseModel):
    """Pagination information for list endpoints."""

    current_page: int = 1
    total_pages: int = 1
    total_items: int | None = None
    has_next: bool = False
    has_previous: bool = False


class HLTVBase(BaseModel):
    """Base model with common serialization helpers."""

    def dict(self, **kwargs: Any) -> dict[str, Any]:
        """Alias for model_dump for backward compatibility."""
        return self.model_dump(**kwargs)

    def json(self, **kwargs: Any) -> str:
        """Alias for model_dump_json for backward compatibility."""
        return self.model_dump_json(**kwargs)

    class Config:
        frozen = False


class HLTVListResponse(BaseModel):
    """Generic wrapper for paginated list responses."""

    items: list[Any] = Field(default_factory=list)
    page: PageInfo = Field(default_factory=PageInfo)
    total: int | None = None
