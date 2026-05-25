"""
SQLModel ORM models for persisting HLTV scraped data.

These models mirror the Pydantic models in src/models/ but add
database-specific fields (primary keys, timestamps, relationships).

Usage:
    from sqlmodel import Session, create_engine
    from src.db.models import CachedMatch

    engine = create_engine("postgresql://user:pass@localhost/hltv")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(CachedMatch(hltv_id=12345, raw_json={...}))
        session.commit()
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import JSON, DateTime, Field, SQLModel


class CachedMatch(SQLModel, table=True):
    """Persistent cache of match data."""

    __tablename__ = "matches"

    id: int | None = Field(default=None, primary_key=True)
    hltv_id: int = Field(unique=True, index=True)
    team1_name: str = ""
    team2_name: str = ""
    team1_id: int | None = None
    team2_id: int | None = None
    event_name: str = ""
    event_id: int | None = None
    match_date: datetime | None = None
    format: str | None = None
    stage: str | None = None
    team1_score: int | None = None
    team2_score: int | None = None
    winner_team1: bool | None = None
    raw_json: str | None = Field(default=None, sa_type=JSON)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_type=DateTime)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        sa_type=DateTime,
    )


class CachedTeam(SQLModel, table=True):
    """Persistent cache of team data."""

    __tablename__ = "teams"

    id: int | None = Field(default=None, primary_key=True)
    hltv_id: int = Field(unique=True, index=True)
    name: str = ""
    country: str | None = None
    rank: int | None = None
    rank_change: int | None = None
    record_wins: int = 0
    record_losses: int = 0
    raw_json: str | None = Field(default=None, sa_type=JSON)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_type=DateTime)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        sa_type=DateTime,
    )


class CachedPlayer(SQLModel, table=True):
    """Persistent cache of player data."""

    __tablename__ = "players"

    id: int | None = Field(default=None, primary_key=True)
    hltv_id: int = Field(unique=True, index=True)
    name: str = ""
    real_name: str | None = None
    country: str | None = None
    team_name: str = ""
    team_id: int | None = None
    rating: float = 0.0
    kills: int = 0
    deaths: int = 0
    adr: float = 0.0
    raw_json: str | None = Field(default=None, sa_type=JSON)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_type=DateTime)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        sa_type=DateTime,
    )


class CachedRanking(SQLModel, table=True):
    """Snapshot of team ranking at a point in time."""

    __tablename__ = "rankings"

    id: int | None = Field(default=None, primary_key=True)
    snapshot_date: datetime = Field(default_factory=datetime.utcnow, index=True)
    raw_json: str | None = Field(default=None, sa_type=JSON)


class CachedRankingEntry(SQLModel, table=True):
    """Individual ranking entry within a snapshot."""

    __tablename__ = "ranking_entries"

    id: int | None = Field(default=None, primary_key=True)
    ranking_id: int | None = Field(default=None, foreign_key="rankings.id")
    rank: int = 0
    team_name: str = ""
    team_id: int | None = None
    points: int = 0
    change: int | None = None


class CachedEvent(SQLModel, table=True):
    """Persistent event/tournament data."""

    __tablename__ = "events"

    id: int | None = Field(default=None, primary_key=True)
    hltv_id: int = Field(unique=True, index=True)
    name: str = ""
    prize_pool: str | None = None
    location: str | None = None
    date_start: datetime | None = None
    date_end: datetime | None = None
    tier: str | None = None
    raw_json: str | None = Field(default=None, sa_type=JSON)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_type=DateTime)


class MatchResult(SQLModel, table=True):
    """Query result for historical match analysis."""

    __tablename__ = "match_results"

    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="matches.id")
    team1_rating: float = 0.0
    team2_rating: float = 0.0
    map_name: str = ""
    team1_score: int = 0
    team2_score: int = 0
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
