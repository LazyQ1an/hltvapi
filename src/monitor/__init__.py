"""
v3.0 Monitoring module — health checks, WebSocket broadcast, webhook alerts.

Features:
- Periodic health checks (parse rate, cache size, warehouse stats)
- WebSocket broadcast to connected clients
- Generic webhook alerts (Discord, Slack, custom)
- Auto-cleanup of stale cache and old data
"""

from __future__ import annotations

from .core import Monitor, get_monitor
from .ws import broadcast, get_client_count, websocket_endpoint

__all__ = ["Monitor", "get_monitor", "broadcast", "get_client_count", "websocket_endpoint"]
