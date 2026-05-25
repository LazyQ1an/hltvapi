"""
Optional PostgreSQL persistence layer for HLTV scraper.

This module requires: pip install sqlmodel[postgresql] psycopg2-binary

It is NOT imported by the main scraper — import explicitly in your scripts.
"""

from __future__ import annotations

from typing import Any


def get_repository(database_url: str = "postgresql://localhost/hltv") -> Any:
    """Get an HLTVRepository instance (lazy import).

    Args:
        database_url: PostgreSQL connection string.

    Returns:
        HLTVRepository instance.

    Raises:
        ImportError: If sqlmodel is not installed.
    """
    try:
        from .repository import HLTVRepository
        return HLTVRepository(database_url)
    except ImportError as e:
        raise ImportError(
            "sqlmodel is required for database persistence. "
            "Install with: pip install sqlmodel[postgresql] psycopg2-binary"
        ) from e


def create_tables(database_url: str = "postgresql://localhost/hltv") -> None:
    """Create all database tables.

    Args:
        database_url: PostgreSQL connection string.
    """
    repo = get_repository(database_url)
    repo.create_tables()


__all__ = ["get_repository", "create_tables"]
