"""
Data warehouse core — SQLite-backed storage for HLTV scraped data.

All operations use raw SQL with Python's built-in sqlite3 module.
No ORM, no external dependencies.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any


_SCHEMA_SQL = """
-- Matches: core match data
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    hltv_id INTEGER UNIQUE NOT NULL,
    team1_name TEXT NOT NULL DEFAULT '',
    team2_name TEXT NOT NULL DEFAULT '',
    team1_id INTEGER,
    team2_id INTEGER,
    team1_score INTEGER,
    team2_score INTEGER,
    event_name TEXT DEFAULT '',
    event_id INTEGER,
    match_format TEXT,
    stage TEXT,
    winner_team1 INTEGER,
    match_date TEXT,
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-map details within a match
CREATE TABLE IF NOT EXISTS match_maps (
    id INTEGER PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(hltv_id),
    map_name TEXT NOT NULL,
    team1_score INTEGER DEFAULT 0,
    team2_score INTEGER DEFAULT 0,
    winner_team1 INTEGER,
    UNIQUE(match_id, map_name)
);

-- Player stats per match
CREATE TABLE IF NOT EXISTS player_match_stats (
    id INTEGER PRIMARY KEY,
    match_id INTEGER NOT NULL,
    player_id INTEGER,
    player_name TEXT NOT NULL,
    team_is_team1 INTEGER NOT NULL DEFAULT 1,
    kills INTEGER DEFAULT 0,
    deaths INTEGER DEFAULT 0,
    assists INTEGER DEFAULT 0,
    adr REAL DEFAULT 0.0,
    rating REAL DEFAULT 0.0,
    kd_diff INTEGER DEFAULT 0,
    UNIQUE(match_id, player_id)
);

-- Team roster snapshots
CREATE TABLE IF NOT EXISTS team_rosters (
    id INTEGER PRIMARY KEY,
    team_id INTEGER NOT NULL,
    team_name TEXT NOT NULL,
    player_id INTEGER,
    player_name TEXT NOT NULL,
    snapshot_date TEXT NOT NULL DEFAULT (date('now')),
    UNIQUE(team_id, player_id, snapshot_date)
);

-- Ranking history (daily snapshots)
CREATE TABLE IF NOT EXISTS rankings_history (
    id INTEGER PRIMARY KEY,
    team_id INTEGER,
    team_name TEXT NOT NULL,
    rank INTEGER NOT NULL,
    points INTEGER DEFAULT 0,
    change INTEGER DEFAULT 0,
    snapshot_date TEXT NOT NULL DEFAULT (date('now'))
);

-- Index for time-range queries
CREATE INDEX IF NOT EXISTS idx_rankings_date ON rankings_history(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_rankings_team ON rankings_history(team_id);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date);
CREATE INDEX IF NOT EXISTS idx_matches_team ON matches(team1_id, team2_id);
CREATE INDEX IF NOT EXISTS idx_player_stats_player ON player_match_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_player_stats_match ON player_match_stats(match_id);

-- Demo archive
CREATE TABLE IF NOT EXISTS demos (
    id INTEGER PRIMARY KEY,
    match_id INTEGER NOT NULL,
    demo_url TEXT NOT NULL,
    filename TEXT,
    map_name TEXT,
    file_size INTEGER,
    downloaded_at TEXT,
    metadata_json TEXT,
    UNIQUE(match_id, demo_url)
);
"""


class Warehouse:
    """SQLite-backed data warehouse for HLTV scraped data.

    Args:
        db_path: Path to SQLite database file.
            Use ':memory:' for in-memory (testing).
    """

    def __init__(self, db_path: str = "hltv_data.sqlite") -> None:
        self._path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    # ── Connection management ────────────────────────────────────

    @property
    def conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self._path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Warehouse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ── Schema ───────────────────────────────────────────────────

    def create_tables(self) -> None:
        """Create all tables if they don't exist."""
        self.conn.executescript(_SCHEMA_SQL)
        self.conn.commit()

    def vacuum(self) -> None:
        """Rebuild database to reclaim space."""
        self.conn.execute("VACUUM")

    # ── Match persistence ────────────────────────────────────────

    def save_match(self, match: Any) -> bool:
        """Save a MatchDetail or MatchOverview.

        Args:
            match: A Pydantic match model.

        Returns:
            True if inserted, False if updated.
        """
        cur = self.conn.execute(
            """INSERT INTO matches
               (hltv_id, team1_name, team2_name, team1_id, team2_id,
                team1_score, team2_score, event_name, event_id,
                match_format, stage, winner_team1, match_date, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(hltv_id) DO UPDATE SET
                team1_score=excluded.team1_score,
                team2_score=excluded.team2_score,
                winner_team1=excluded.winner_team1,
                raw_json=excluded.raw_json,
                updated_at=datetime('now')""",
            (
                match.id,
                getattr(match.team1, "name", ""),
                getattr(match.team2, "name", ""),
                getattr(match.team1, "id", None),
                getattr(match.team2, "id", None),
                getattr(match.team1, "score", None),
                getattr(match.team2, "score", None),
                getattr(match.event, "name", ""),
                getattr(match.event, "id", None),
                getattr(match, "format", None),
                getattr(match, "stage", None),
                getattr(match, "winner_team1", None),
                str(match.date) if hasattr(match, "date") and match.date else None,
                match.model_dump_json() if hasattr(match, "model_dump_json") else None,
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def save_match_maps(self, match_id: int, maps: list[Any]) -> None:
        """Save per-map scores for a match."""
        for mp in maps:
            self.conn.execute(
                """INSERT OR IGNORE INTO match_maps
                   (match_id, map_name, team1_score, team2_score, winner_team1)
                   VALUES (?,?,?,?,?)""",
                (
                    match_id,
                    str(getattr(getattr(mp, "name", ""), "value", getattr(mp, "name", "Unknown"))),
                    getattr(mp, "team1_score", 0),
                    getattr(mp, "team2_score", 0),
                    getattr(mp, "winner_team1", None),
                ),
            )
        self.conn.commit()

    # ── Ranking persistence ──────────────────────────────────────

    def save_ranking_snapshot(self, ranking: Any) -> None:
        """Save daily ranking snapshot with timestamp.

        Args:
            ranking: A TeamRanking model.
        """
        today = datetime.utcnow().date().isoformat()
        for entry in ranking.teams:
            self.conn.execute(
                """INSERT INTO rankings_history
                   (team_id, team_name, rank, points, change, snapshot_date)
                   VALUES (?,?,?,?,?,?)""",
                (entry.team_id, entry.name, entry.rank, entry.points, entry.change or 0, today),
            )
        self.conn.commit()

    # ── Player stats persistence ─────────────────────────────────

    def save_player_stats(self, match_id: int, players: list[Any], team_is_team1: bool = True) -> None:
        """Save per-player match stats."""
        for p in players:
            pid = getattr(getattr(p, "player", None), "id", None) or getattr(p, "id", None)
            pname = getattr(getattr(p, "player", None), "name", "") or getattr(p, "name", "")
            self.conn.execute(
                """INSERT OR REPLACE INTO player_match_stats
                   (match_id, player_id, player_name, team_is_team1,
                    kills, deaths, assists, adr, rating, kd_diff)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    match_id, pid, pname, int(team_is_team1),
                    getattr(p, "kills", 0), getattr(p, "deaths", 0),
                    getattr(p, "assists", 0), getattr(p, "adr", 0.0),
                    getattr(p, "rating", 0.0), getattr(p, "kd_diff", 0),
                ),
            )
        self.conn.commit()

    # ── Demo archive ─────────────────────────────────────────────

    def register_demo(self, match_id: int, demo_url: str, filename: str | None = None,
                      map_name: str | None = None, file_size: int | None = None) -> bool:
        """Register a demo in the archive.

        Returns:
            True if newly inserted.
        """
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO demos
               (match_id, demo_url, filename, map_name, file_size)
               VALUES (?,?,?,?,?)""",
            (match_id, demo_url, filename, map_name, file_size),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def mark_demo_downloaded(self, demo_url: str, file_size: int | None = None) -> None:
        """Mark a demo as downloaded."""
        self.conn.execute(
            "UPDATE demos SET downloaded_at=datetime('now'), file_size=? WHERE demo_url=?",
            (file_size, demo_url),
        )
        self.conn.commit()

    # ── Queries ──────────────────────────────────────────────────

    def query_matches(
        self,
        team_name: str | None = None,
        event_name: str | None = None,
        days: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query matches with flexible filters.

        Args:
            team_name: Filter by team name (partial match).
            event_name: Filter by event name (partial match).
            days: Only matches within last N days.
            limit: Max results.

        Returns:
            List of match dicts.
        """
        sql = "SELECT * FROM matches WHERE 1=1"
        params: list[Any] = []

        if team_name:
            sql += " AND (team1_name LIKE ? OR team2_name LIKE ?)"
            params.extend(["%" + team_name + "%", "%" + team_name + "%"])

        if event_name:
            sql += " AND event_name LIKE ?"
            params.append("%" + event_name + "%")

        if days is not None:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            sql += " AND match_date >= ?"
            params.append(cutoff)

        sql += " ORDER BY match_date DESC LIMIT ?"
        params.append(limit)

        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def get_player_history(
        self,
        player_id: int | None = None,
        player_name: str | None = None,
        days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get a player's historical match stats.

        Args:
            player_id: HLTV player ID.
            player_name: Player name (used if player_id is None).
            days: Only matches within last N days.

        Returns:
            List of player match stat dicts.
        """
        sql = """SELECT ps.*, m.event_name, m.match_date, m.team1_name, m.team2_name,
                        m.team1_score, m.team2_score
                 FROM player_match_stats ps
                 JOIN matches m ON ps.match_id = m.hltv_id
                 WHERE (ps.player_id = ? OR (ps.player_id IS NULL AND ps.player_name LIKE ?))"""
        params: list[Any] = [player_id, "%" + (player_name or "") + "%"]

        if days is not None:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            sql += " AND m.match_date >= ?"
            params.append(cutoff)

        sql += " ORDER BY m.match_date DESC"
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def get_rankings_history(
        self,
        team_id: int | None = None,
        team_name: str | None = None,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """Get ranking history for a team.

        Args:
            team_id: HLTV team ID.
            team_name: Team name (used if team_id is None).
            days: Lookback period.

        Returns:
            List of {date, rank, points} dicts.
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        sql = """SELECT snapshot_date, rank, points, change
                 FROM rankings_history
                 WHERE snapshot_date >= ?
                   AND (team_id = ? OR team_name LIKE ?)
                 ORDER BY snapshot_date ASC"""
        params: list[Any] = [cutoff, team_id, "%" + (team_name or "") + "%"]
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def get_pending_demos(self) -> list[dict[str, Any]]:
        """Get demos not yet downloaded."""
        rows = self.conn.execute(
            "SELECT * FROM demos WHERE downloaded_at IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict[str, int]:
        """Get database statistics."""
        cur = self.conn
        return {
            "matches": cur.execute("SELECT COUNT(*) FROM matches").fetchone()[0],
            "match_maps": cur.execute("SELECT COUNT(*) FROM match_maps").fetchone()[0],
            "player_stats": cur.execute("SELECT COUNT(*) FROM player_match_stats").fetchone()[0],
            "rankings": cur.execute("SELECT COUNT(*) FROM rankings_history").fetchone()[0],
            "demos": cur.execute("SELECT COUNT(*) FROM demos").fetchone()[0],
        }
