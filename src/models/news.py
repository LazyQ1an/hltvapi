"""
Pydantic models for news/article data from HLTV.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NewsArticle(BaseModel):
    """A news article from HLTV."""

    id: int | None = None
    """HLTV news ID."""
    title: str = ""
    """Article title."""
    description: str | None = None
    """Article short description / summary."""
    url: str | None = None
    """Article URL."""
    image: str | None = None
    """Article thumbnail image URL."""
    date: datetime | None = None
    """Publication date."""
    category: str | None = None
    """Article category (e.g., 'News', 'Interview', 'Analysis')."""
    author: str | None = None
    """Article author name."""


class NewsDetail(NewsArticle):
    """Full article content."""

    content: str = ""
    """Full article HTML/text content."""
    related_articles: list[NewsArticle] = Field(default_factory=list)
    """Related article links."""


class NewsListResponse(BaseModel):
    """Wrapper for paginated news listing."""

    articles: list[NewsArticle] = Field(default_factory=list)
    total: int | None = None
    offset: int = 0
