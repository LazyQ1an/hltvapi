"""Pydantic v2 models for all HLTV data structures."""

from .common import (
    Event,
    HLTVBase,
    HLTVListResponse,
    MapName,
    MapScore,
    PageInfo,
    Player,
    PlayerStats,
    Team,
    TeamRecord,
)
from .event import EventDetail, EventGroup, EventOverview
from .match import (
    MatchDemo,
    MatchDetail,
    MatchEvent,
    MatchMap,
    MatchOverview,
    MatchTeam,
    PlayerMatchStats,
)
from .news import NewsArticle, NewsDetail, NewsListResponse
from .player import (
    PlayerAchievement,
    PlayerDetailed,
    PlayerMapStats,
    TopPlayer,
    TopPlayersResponse,
)
from .team import (
    TeamDetail,
    TeamRanking,
    TeamRankingEntry,
    TeamRosterPlayer,
)

__all__ = [
    # Common
    "Event",
    "HLTVBase",
    "HLTVListResponse",
    "MapName",
    "MapScore",
    "PageInfo",
    "Player",
    "PlayerStats",
    "Team",
    "TeamRecord",
    # Event
    "EventDetail",
    "EventGroup",
    "EventOverview",
    # Match
    "MatchDemo",
    "MatchDetail",
    "MatchEvent",
    "MatchMap",
    "MatchOverview",
    "MatchTeam",
    "PlayerMatchStats",
    # News
    "NewsArticle",
    "NewsDetail",
    "NewsListResponse",
    # Player
    "PlayerAchievement",
    "PlayerDetailed",
    "PlayerMapStats",
    "TopPlayer",
    "TopPlayersResponse",
    # Team
    "TeamDetail",
    "TeamRanking",
    "TeamRankingEntry",
    "TeamRosterPlayer",
]
