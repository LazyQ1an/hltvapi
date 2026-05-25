"""
WebSocket broadcast system for real-time monitoring alerts.

Provides:
- WebSocket endpoint for the FastAPI server (/ws)
- broadcast() function for pushing alerts to all connected clients
- Connection lifecycle management

Usage:
    # In api.py — mount the WebSocket endpoint
    from src.monitor.ws import websocket_endpoint
    app.add_websocket_route("/ws", websocket_endpoint)

    # From monitor — broadcast alert to all clients
    from src.monitor.ws import broadcast
    await broadcast("Alert message")
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("hltv.monitor.ws")

# Shared set of connected WebSocket clients
_connected_clients: set[WebSocket] = set()


async def _heartbeat_loop(websocket: WebSocket, interval: float = 30.0) -> None:
    """Send periodic ping frames to keep connection alive."""
    try:
        while websocket in _connected_clients:
            await asyncio.sleep(interval)
            await websocket.send_json({"type": "ping"})
    except Exception:
        # Connection likely closed
        pass


async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint — handles client connections.

    Usage in api.py:
        from fastapi import WebSocket
        from src.monitor.ws import websocket_endpoint
        @app.websocket("/ws")
        async def ws(websocket: WebSocket):
            await websocket_endpoint(websocket)
    """
    await websocket.accept()
    _connected_clients.add(websocket)
    logger.info("WebSocket client connected (%d total)", len(_connected_clients))

    heartbeat_task: asyncio.Task | None = None
    try:
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "message": "HLTV API Monitor WebSocket connected",
        })

        # Heartbeat task to keep connection alive and detect stale clients
        heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket))

        # Keep connection alive, handle incoming messages
        async for message in websocket.iter_text():
            try:
                data = json.loads(message)
                msg_type = data.get("type", "")
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg_type == "subscribe":
                    logger.debug("Client subscribed to alerts")
                    await websocket.send_json({
                        "type": "subscribed",
                        "channel": data.get("channel", "alerts"),
                    })
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON",
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WebSocket error: %s", e)
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
        _connected_clients.discard(websocket)
        logger.info("WebSocket client disconnected (%d remaining)", len(_connected_clients))


async def broadcast(message: str) -> int:
    """Broadcast a message to all connected WebSocket clients.

    Args:
        message: JSON string to broadcast.

    Returns:
        Number of clients the message was sent to.
    """
    disconnected: list[WebSocket] = []
    count = 0

    for client in _connected_clients:
        try:
            await client.send_text(message)
            count += 1
        except Exception:
            disconnected.append(client)

    # Clean up disconnected clients
    for client in disconnected:
        _connected_clients.discard(client)

    if disconnected:
        logger.debug("Cleaned up %d disconnected clients", len(disconnected))

    return count


def get_client_count() -> int:
    """Get number of currently connected WebSocket clients."""
    return len(_connected_clients)
