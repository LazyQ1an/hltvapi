"""
HLTV Pro Scraper v4.1 — Integration & Polish Edition.

Async-first, anti-bot CS2 data API for HLTV.org with full observability,
multi-tier caching, export center, and Next.js 15 dashboard.

Key features:
    - Async-first architecture (asyncio + httpx + curl_cffi)
    - Anti-bot measures (User-Agent rotation, TLS fingerprinting, Playwright)
    - Pydantic v2 models throughout
    - Three-tier cache (L1 memory + L2 LRU/TTL + L3 diskcache/Redis)
    - Adaptive rate limiting with exponential backoff
    - OpenTelemetry + Prometheus observability
    - IP rate limiting + API key + Security headers
    - Export center (PDF + Excel)
    - CLI (Typer) and REST API (FastAPI) interfaces

Usage:
    from src.client import HLTVClient
    from src.config import HLTVConfig
    from src.endpoints.matches import MatchesEndpoint

    config = HLTVConfig.load()
    async with HLTVClient(config) as client:
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

__version__ = "4.1.0"
