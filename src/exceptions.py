"""
Custom exceptions for the HLTV scraper.

Defines a hierarchy of domain-specific exceptions to provide
granular error handling throughout the scraping pipeline.
"""

from __future__ import annotations


class HLTVException(Exception):
    """Base exception for all HLTV scraper errors."""

    def __init__(self, message: str, original: Exception | None = None) -> None:
        self.message = message
        self.original = original
        super().__init__(self.message)


class ConfigError(HLTVException):
    """Raised when configuration is invalid or missing."""


class HTTPError(HLTVException):
    """Raised on HTTP-level failures (non-200, timeout, connection)."""

    def __init__(self, message: str, status_code: int | None = None, url: str | None = None, original: Exception | None = None) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message, original=original)


class RateLimitError(HTTPError):
    """Raised when rate limiting is detected (HTTP 429 or similar)."""


class BlockedError(HTTPError):
    """Raised when the scraper is blocked (Cloudflare challenge, 403, 503)."""


class ParseError(HLTVException):
    """Raised when parsing HLTV HTML fails."""

    def __init__(self, message: str, url: str | None = None, html_snippet: str | None = None, original: Exception | None = None) -> None:
        self.url = url
        self.html_snippet = html_snippet
        super().__init__(message, original=original)


class NotFoundError(HLTVException):
    """Raised when a requested resource is not found (404)."""

    def __init__(self, message: str, resource_type: str | None = None, resource_id: str | int | None = None) -> None:
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(message)


class CacheError(HLTVException):
    """Raised on cache backend failures."""
