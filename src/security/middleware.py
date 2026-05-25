"""
IP-based rate limiting middleware.

v4.0: Lightweight in-memory rate limiter per client IP.
For production at scale, replace with Redis-backed implementation.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class IPRateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory IP-based rate limiter.

    Tracks request timestamps per IP within a sliding window.
    Returns 429 when limit is exceeded.

    Args:
        max_requests: Max requests allowed per window.
        window_seconds: Sliding window duration in seconds.
    """

    def __init__(
        self,
        app,
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self._max_requests = max_requests
        self._window = window_seconds
        self._store: dict[str, list[float]] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        """Resolve real client IP, respecting reverse proxy headers.

        Uses X-Forwarded-For when behind a trusted proxy,
        falls back to direct client IP.
        """
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take the leftmost IP (original client) from the chain
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(
        self, request: Request, call_next: Callable,
    ) -> JSONResponse:
        client_ip = self._get_client_ip(request)

        # Skip health check and metrics endpoints
        skip_paths = {"/health", "/metrics", "/favicon.ico"}
        if request.url.path in skip_paths:
            return await call_next(request)

        now = time.time()

        # Clean expired entries
        self._store[client_ip] = [
            t
            for t in self._store[client_ip]
            if now - t < self._window
        ]

        if len(self._store[client_ip]) >= self._max_requests:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too many requests",
                    "retry_after_seconds": self._window,
                },
                headers={"Retry-After": str(self._window)},
            )

        self._store[client_ip].append(now)
        return await call_next(request)

    def cleanup(self) -> None:
        """Periodic cleanup of expired entries.

        Should be called from scheduler or background task.
        """
        now = time.time()
        expired_ips = [
            ip
            for ip, timestamps in self._store.items()
            if all(now - t >= self._window for t in timestamps)
        ]
        for ip in expired_ips:
            del self._store[ip]
