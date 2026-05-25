"""HLTV scraper endpoint modules."""

from .demos import DemosEndpoint
from .events import EventsEndpoint
from .matches import MatchesEndpoint
from .news import NewsEndpoint
from .players import PlayersEndpoint
from .results import ResultsEndpoint
from .search import SearchEndpoint
from .stats import StatsEndpoint
from .teams import TeamsEndpoint

__all__ = [
    "DemosEndpoint",
    "EventsEndpoint",
    "MatchesEndpoint",
    "NewsEndpoint",
    "PlayersEndpoint",
    "ResultsEndpoint",
    "SearchEndpoint",
    "StatsEndpoint",
    "TeamsEndpoint",
]