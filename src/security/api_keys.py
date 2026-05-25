"""
API Key management for HLTV API v4.0.

Supports:
- Environment variable based API keys (HLTV_API_KEY)
- Multiple keys with optional labels
- Key validation middleware
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Load API keys from environment
# Format: HLTV_API_KEYS=key1:label1,key2:label2
# Or single key: HLTV_API_KEY=my-secret-key
_raw = os.getenv("HLTV_API_KEYS", "")
_single = os.getenv("HLTV_API_KEY", "")

_valid_keys: dict[str, str] = {}

if _raw:
    for item in _raw.split(","):
        parts = item.strip().split(":", 1)
        key = parts[0].strip()
        label = parts[1].strip() if len(parts) > 1 else "default"
        if key:
            _valid_keys[key] = label
elif _single:
    _valid_keys[_single] = "default"


def verify_api_key(
    api_key: Annotated[str | None, Security(API_KEY_HEADER)] = None,
) -> str | None:
    """Verify API key from request header.

    If no API keys are configured, all requests pass (no auth required).
    If API keys are configured, requests must include a valid key.

    Returns:
        Key label if valid, or raises HTTPException.

    Raises:
        HTTPException 401: Invalid or missing API key.
    """
    # No keys configured → auth is disabled
    if not _valid_keys:
        return None

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide X-API-Key header.",
        )

    if api_key not in _valid_keys:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key.",
        )

    return _valid_keys[api_key]


# FastAPI dependency for route-level protection
APIKeyDep = Depends(verify_api_key)


def is_auth_enabled() -> bool:
    """Check if API key authentication is configured."""
    return len(_valid_keys) > 0
