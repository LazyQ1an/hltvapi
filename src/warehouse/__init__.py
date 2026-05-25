"""
Data warehouse for HLTV scraped data.

Built on SQLite (stdlib, no external deps).
Supports:
- Storing matches, player stats, team data, rankings
- Historical snapshots (daily ranking records)
- Time-range queries
- Demo archive management

Usage:
    from src.warehouse import Warehouse

    db = Warehouse("hltv_data.db")
    db.create_tables()
    db.save_match(match_detail)
    db.save_ranking(ranking)
    db.get_player_history(player_id=7993, days=90)
"""

from __future__ import annotations

from .core import Warehouse

__all__ = ["Warehouse"]
