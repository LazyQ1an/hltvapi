"""
Repository layer for persisting scraped HLTV data to PostgreSQL.

This module provides convenience methods to save scraper results
into the database, enabling time-series analysis and historical queries.

Usage:
    from sqlmodel import Session, create_engine
    from src.db.repository import HLTVRepository

    engine = create_engine("postgresql://user:pass@localhost/hltv")
    repo = HLTVRepository(engine)

    # After scraping
    matches = await matches_endpoint.get_upcoming()
    for match in matches:
        repo.save_match(match)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, create_engine, select


class HLTVRepository:
    """Repository for persisting and querying HLTV data.

    Args:
        database_url: PostgreSQL connection string.
            Default: "postgresql://localhost/hltv"
    """

    def __init__(self, database_url: str = "postgresql://localhost/hltv") -> None:
        self.engine = create_engine(database_url)

    def create_tables(self) -> None:
        """Create all database tables (if not exist)."""
        from .models import CachedMatch, CachedTeam, CachedPlayer, CachedRanking, CachedEvent  # noqa: F401
        from sqlmodel import SQLModel
        SQLModel.metadata.create_all(self.engine)

    # ── Match persistence ─────────────────────────────────────────

    def save_match(self, match: Any) -> bool:
        """Save a MatchOverview or MatchDetail to the database.

        Args:
            match: A MatchOverview or MatchDetail Pydantic model.

        Returns:
            True if saved, False if duplicate (already exists).
        """
        from .models import CachedMatch

        with Session(self.engine) as session:
            existing = session.exec(
                select(CachedMatch).where(CachedMatch.hltv_id == match.id)
            ).first()
            if existing:
                # Update existing
                existing.team1_score = match.team1.score if hasattr(match.team1, 'score') else None
                existing.team2_score = match.team2.score if hasattr(match.team2, 'score') else None
                existing.raw_json = match.model_dump_json()
                session.add(existing)
                session.commit()
                return False

            db_match = CachedMatch(
                hltv_id=match.id,
                team1_name=match.team1.name,
                team2_name=match.team2.name,
                team1_id=match.team1.id,
                team2_id=match.team2.id,
                event_name=match.event.name if hasattr(match.event, 'name') else "",
                event_id=match.event.id if hasattr(match.event, 'id') else None,
                match_date=match.date,
                format=match.format,
                stage=match.stage,
                team1_score=match.team1.score if hasattr(match.team1, 'score') else None,
                team2_score=match.team2.score if hasattr(match.team2, 'score') else None,
                winner_team1=match.winner_team1 if hasattr(match, 'winner_team1') else None,
                raw_json=match.model_dump_json(),
            )
            session.add(db_match)
            session.commit()
            return True

    # ── Ranking persistence ───────────────────────────────────────

    def save_ranking(self, ranking: Any) -> bool:
        """Save a TeamRanking snapshot to the database.

        Args:
            ranking: A TeamRanking Pydantic model.

        Returns:
            True if saved.
        """
        from .models import CachedRanking, CachedRankingEntry

        with Session(self.engine) as session:
            db_ranking = CachedRanking(
                snapshot_date=ranking.date or datetime.utcnow(),
                raw_json=ranking.model_dump_json(),
            )
            session.add(db_ranking)
            session.flush()  # Get the ranking.id

            for entry in ranking.teams:
                db_entry = CachedRankingEntry(
                    ranking_id=db_ranking.id,
                    rank=entry.rank,
                    team_name=entry.name,
                    team_id=entry.team_id,
                    points=entry.points,
                    change=entry.change,
                )
                session.add(db_entry)

            session.commit()
            return True

    # ── Query helpers ─────────────────────────────────────────────

    def get_match_by_id(self, hltv_id: int) -> Any | None:
        """Get a match from the database by HLTV ID."""
        from .models import CachedMatch

        with Session(self.engine) as session:
            return session.exec(
                select(CachedMatch).where(CachedMatch.hltv_id == hltv_id)
            ).first()

    def get_team_rankings_history(self, team_id: int) -> list[dict[str, Any]]:
        """Get ranking history for a team across snapshots.

        Returns:
            List of {date, rank, points} dicts.
        """
        from .models import CachedRanking, CachedRankingEntry

        with Session(self.engine) as session:
            results = session.exec(
                select(CachedRankingEntry, CachedRanking.snapshot_date)
                .join(CachedRanking, CachedRankingEntry.ranking_id == CachedRanking.id)
                .where(CachedRankingEntry.team_id == team_id)
                .order_by(CachedRanking.snapshot_date)
            ).all()

            return [
                {"date": str(r[1]), "rank": r[0].rank, "points": r[0].points}
                for r in results
            ]

    def get_stats(self) -> dict[str, int]:
        """Get database statistics."""
        from sqlmodel import func
        from .models import CachedMatch, CachedTeam, CachedPlayer, CachedRanking

        with Session(self.engine) as session:
            return {
                "matches": session.exec(select(func.count(CachedMatch.id))).one(),
                "teams": session.exec(select(func.count(CachedTeam.id))).one(),
                "players": session.exec(select(func.count(CachedPlayer.id))).one(),
                "rankings": session.exec(select(func.count(CachedRanking.id))).one(),
            }

    def clear_all(self) -> None:
        """Clear all cached data (for testing)."""
        from .models import CachedMatch, CachedTeam, CachedPlayer, CachedRanking, CachedEvent
        from sqlmodel import delete as sa_delete
        with Session(self.engine) as session:
            for model in [CachedMatch, CachedTeam, CachedPlayer, CachedRanking, CachedEvent]:
                session.exec(sa_delete(model))
            session.commit()
