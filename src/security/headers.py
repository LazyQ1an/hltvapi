"""
Security HTTP headers middleware.

Adds recommended security headers to all API responses:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- X-XSS-Protection
- Referrer-Policy
- Strict-Transport-Security (HSTS)
- Cache-Control policy
"""

from __future__ import annotations

from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security-related HTTP headers to all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        import os
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        }
        # HSTS only in production to avoid local dev issues
        if os.environ.get("ENV", "development") == "production":
            headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # Aggressive no-cache for export endpoints
        if request.url.path.startswith("/export"):
            headers["Cache-Control"] = "no-store"
        else:
            headers["Cache-Control"] = "public, max-age=60"

        for key, value in headers.items():
            if key not in response.headers:
                response.headers[key] = value

        return response
