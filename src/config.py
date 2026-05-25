"""
Configuration management for HLTV scraper.

Uses pydantic-settings with YAML file support. Configuration can be
set via config file, environment variables, or programmatic overrides.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml

from src.exceptions import ConfigError

DEFAULT_CONFIG_PATHS: list[Path] = [
    Path("config.yaml"),
    Path("config.yml"),
    Path("config.example.yaml"),
]


class RateLimitConfig(BaseSettings):
    """Rate limiting configuration."""

    enabled: bool = True
    """Whether rate limiting is enabled."""

    min_delay: float = 1.5
    """Minimum delay between requests in seconds (gaussian center)."""

    max_delay: float = 3.0
    """Maximum delay between requests in seconds."""

    jitter: bool = True
    """Add random gaussian jitter to delays."""

    requests_per_minute: int | None = None
    """Hard cap on requests per minute (None = no cap)."""

    requests_per_hour: int = 1000
    """Hard cap on requests per hour. Reset hourly."""

    requests_per_day: int = 5000
    """Hard cap on requests per day. Reset daily."""


class CacheConfig(BaseSettings):
    """Cache backend configuration."""

    backend: Literal["diskcache", "redis", "none"] = "diskcache"
    """Cache backend to use."""

    ttl: int = 300
    """Default cache TTL in seconds (5 minutes)."""

    diskcache_dir: str = ".cache/hltv"
    """Directory for diskcache storage."""

    redis_url: str = "redis://localhost:6379/0"
    """Redis connection URL."""


class ClientConfig(BaseSettings):
    """HTTP client and anti-bot configuration."""

    mode: Literal["light", "stealth"] = "light"
    """Request mode: 'light' = httpx/curl_cffi only, 'stealth' = use Playwright when needed."""

    timeout: int = 30
    """Request timeout in seconds."""

    max_retries: int = 3
    """Maximum retry attempts per request."""

    retry_delay: float = 1.0
    """Base delay between retries in seconds."""

    retry_backoff: float = 2.0
    """Exponential backoff multiplier."""

    retry_on_status: list[int] = Field(default_factory=lambda: [429, 500, 502, 503, 504])
    """HTTP status codes that trigger a retry."""

    user_agent_rotation: bool = True
    """Rotate User-Agent headers."""

    referer_rotation: bool = True
    """Set realistic Referer headers."""

    curl_impersonate: bool = True
    """Use curl_cffi for TLS fingerprint impersonation."""

    curl_impersonate_version: str = "chrome124"
    """Browser version to impersonate (e.g., 'chrome124', 'chrome130', 'safari17')."""

    max_concurrency: int = 5
    """Maximum number of concurrent requests. Set to 2 for low-resource deployment."""

    proxy: str | None = None
    """Proxy URL (e.g., 'http://user:pass@host:port' or 'socks5://host:port').
    Also supports HTTPS_PROXY / HTTP_PROXY env vars."""


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    level: str = "INFO"
    """Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""

    format: Literal["json", "plain"] = "plain"
    """Log output format."""

    file: str | None = None
    """Optional log file path."""


class HLTVConfig(BaseSettings):
    """Root configuration for the HLTV scraper."""

    model_config = SettingsConfigDict(
        env_prefix="HLTV_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    base_url: str = "https://www.hltv.org"
    """Base URL for HLTV."""

    robots_check: bool = True
    """Check robots.txt before scraping."""

    respect_robots: bool = True
    """Respect robots.txt rules."""

    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    """Default User-Agent string."""

    rate_limit: RateLimitConfig = RateLimitConfig()
    """Rate limiting configuration."""

    cache: CacheConfig = CacheConfig()
    """Cache configuration."""

    client: ClientConfig = ClientConfig()
    """HTTP client configuration."""

    logging: LoggingConfig = LoggingConfig()
    """Logging configuration."""

    @classmethod
    def load(cls, path: str | Path | None = None) -> HLTVConfig:
        """Load configuration from a YAML file, falling back to defaults.

        Args:
            path: Path to YAML config file. If None, search in default locations.

        Returns:
            HLTVConfig instance with merged settings.

        Raises:
            ConfigError: If a specified config file cannot be loaded.
        """
        if path is not None:
            config_path = Path(path)
            if not config_path.exists():
                raise ConfigError(f"Config file not found: {config_path}")
            return cls._from_yaml(config_path)

        for default_path in DEFAULT_CONFIG_PATHS:
            if default_path.exists():
                return cls._from_yaml(default_path)

        return cls()

    @classmethod
    def _from_yaml(cls, path: Path) -> HLTVConfig:
        """Load config from a YAML file, merging with defaults.

        Args:
            path: Path to the YAML file.

        Returns:
            HLTVConfig instance.
        """
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            return cls()

        # Recursively resolve nested keys into pydantic model structure
        # e.g., {"rate_limit": {"min_delay": 0.5}} -> nested init
        return cls(**data)


__all__ = [
    "CacheConfig",
    "ClientConfig",
    "HLTVConfig",
    "LoggingConfig",
    "RateLimitConfig",
]
