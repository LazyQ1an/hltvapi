"""
Pydantic models for event/tournament data from HLTV.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .team import TeamRankingEntry


class EventOverview(BaseModel):
    """Summary of an event, used in event listings."""

    id: int | None = None
    """HLTV event ID."""
    name: str = ""
    """Event name."""
    logo: str | None = None
    """Event logo URL."""
    date_start: datetime | None = None
    """Event start date."""
    date_end: datetime | None = None
    """Event end date."""
    prize_pool: str | None = None
    """Prize pool display (e.g., '$1,000,000')."""
    location: str | None = None
    """Event location/city."""
    teams_count: int | None = None
    """Number of participating teams."""
    tier: str | None = None
    """Event tier (e.g., 'S-Tier', 'A-Tier')."""
    is_ongoing: bool = False
    """Whether the event is currently running."""


class EventDetail(EventOverview):
    """Full event details including participants and standings."""

    teams: list[TeamRankingEntry] = Field(default_factory=list)
    """Participating teams (if available)."""
    format_description: str | None = None
    """Event format description."""
    organizer: str | None = None
    """Event organizer (e.g., 'ESL', 'BLAST')."""
    streams: list[dict[str, str]] = Field(default_factory=list)
    """Stream links [{'name': 'Twitch', 'url': '...'}]."""
    related_events: list[EventOverview] = Field(default_factory=list)
    """Related or qualifying events."""


class EventGroup(BaseModel):
    """A group stage within an event."""

    name: str = ""
    """Group name (e.g., 'Group A')."""
    teams: list[TeamRankingEntry] = Field(default_factory=list)
    """Teams in the group."""
