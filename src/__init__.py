"""
HLTV Pro API NG1.0 -- Single-IP Cloudflare bypass for HLTV.org.

Async-first, anti-bot CS2 data API with:
- SessionPool with TLS fingerprint rotation
- FetchPipeline for unified request execution
- BlockDetector with 5-layer confidence scoring
- AdaptiveRateLimiter with sliding windows
- HumanRequestPattern with Markov-chain navigation
- Three-tier cache (L1 mem -> L2 LRU/TTL -> L3 diskcache/Redis)
- SemanticParser with multi-selector fallback
- LiveMatchTracker with adaptive polling
- FastAPI REST API + Typer CLI

Usage:
    from src import HLTVClient, HLTVConfig

    config = HLTVConfig.load()
    async with HLTVClient(config) as client:
        from src.endpoints.matches import MatchesEndpoint
        matches = await MatchesEndpoint(client).get_upcoming()
"""

from .client import HLTVClient
from .config import HLTVConfig
from .exceptions import (
    BlockedError,
    CacheError,
    ConfigError,
    HLTVException,
    HTTPError,
    NotFoundError,
    ParseError,
    RateLimitError,
)

__all__ = [
    "HLTVClient",
    "HLTVConfig",
    "BlockedError",
    "CacheError",
    "ConfigError",
    "HLTVException",
    "HTTPError",
    "NotFoundError",
    "ParseError",
    "RateLimitError",
]

__version__ = "5.0.0"
