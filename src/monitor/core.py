"""
Monitor core — health checks, alerts, and auto-cleanup.

Designed for low-resource deployments.
All cleanup runs on a background asyncio task.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as tmod
from pathlib import Path
from typing import Any

logger = logging.getLogger("hltv.monitor")

# Singleton
_monitor_instance: Monitor | None = None


def get_monitor() -> Monitor:
    """Get the global Monitor instance."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = Monitor()
    return _monitor_instance


class Monitor:
    """Health monitor with periodic checks, alerts, and cleanup.

    Usage:
        monitor = Monitor()
        await monitor.start(client, warehouse, config)
        # ... runs in background ...
        await monitor.stop()
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._client: Any = None
        self._warehouse: Any = None
        self._config: dict[str, Any] = {}
        self._running = False

    async def start(self, client: Any, warehouse: Any | None = None,
                    config: dict[str, Any] | None = None) -> None:
        """Start the background monitoring loop.

        Args:
            client: HLTVClient instance.
            warehouse: Optional Warehouse instance.
            config: Monitoring config dict.
        """
        self._client = client
        self._warehouse = warehouse
        self._config = config or {}
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Monitor started (interval=%ds)", self._get("check_interval", 300))

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Monitor stopped")

    def _get(self, key: str, default: Any = None) -> Any:
        """Get a config value with dot-notation support."""
        keys = key.split(".")
        val = self._config
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k, {})
            else:
                return default
        return val if val != {} else default

    async def _run_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check()
            except Exception as e:
                logger.warning("Monitor check failed: %s", e)
            await asyncio.sleep(self._get("check_interval", 300))

    async def _check(self) -> None:
        """Run a single health check cycle."""
        alerts: list[str] = []

        # 1. Parse ratio check
        try:
            from src.utils.parsestats import report_all
            stats = report_all()
            threshold = self._get("parse_ratio_threshold", 0.75)
            for name, s in stats.items():
                if s["total"] > 0 and s["ratio"] < threshold:
                    msg = "Low parse ratio: {} ({:.0f}%)".format(name, s["ratio"] * 100)
                    alerts.append(msg)
                    logger.warning(msg)
        except Exception:
            pass

        # 2. Rate limiter status
        if self._client:
            try:
                limiter = self._client._rate_limiter.get_stats()
                hourly_used = limiter.get("hourly_used", 0)
                hourly_limit = limiter.get("hourly_limit", 1)
                pct = (hourly_used / hourly_limit) * 100
                if pct > 90:
                    alerts.append("Hourly rate limit at {:.0f}%".format(pct))
            except Exception:
                pass

        # 3. Cache cleanup
        try:
            await self._cleanup_cache()
        except Exception as e:
            logger.warning("Cache cleanup failed: %s", e)

        # 4. Data retention cleanup
        try:
            self._cleanup_data()
        except Exception as e:
            logger.warning("Data cleanup failed: %s", e)

        # Send alerts if any
        if alerts:
            await self._send_alerts(alerts)

    async def _cleanup_cache(self) -> None:
        """Clean up old diskcache entries."""
        config = self._client.config if self._client else None
        if not config:
            return
        try:
            cache_dir = getattr(config.cache, "diskcache_dir", ".cache/hltv")
            cache_path = Path(cache_dir)
            if cache_path.exists():
                # Remove files older than auto_cleanup_days
                cleanup_days = 7
                cutoff = tmod.time() - (cleanup_days * 86400)
                count = 0
                for f in cache_path.rglob("*"):
                    if f.is_file() and f.stat().st_mtime < cutoff:
                        f.unlink(missing_ok=True)
                        count += 1
                if count > 0:
                    logger.info("Cleaned %d stale cache entries", count)
        except Exception:
            pass

    def _cleanup_data(self) -> None:
        """Clean up old warehouse data and logs."""
        if not self._warehouse:
            return
        try:
            keep_days = 90
            # SQLite cleanup — DELETE first, VACUUM only occasionally (expensive)
            self._warehouse.conn.execute(
                "DELETE FROM matches WHERE match_date < date('now', '-' || ? || ' days')",
                (keep_days,),
            )
            self._warehouse.conn.execute(
                "DELETE FROM rankings_history WHERE snapshot_date < date('now', '-' || ? || ' days')",
                (keep_days,),
            )
            self._warehouse.conn.commit()
            # VACUUM is I/O intensive and locks the DB — run only ~weekly
            import random
            if random.random() < 0.015:  # ~1/67 chance per run ≈ weekly at 5min intervals
                self._warehouse.conn.execute("VACUUM")
                logger.info("VACUUM executed during cleanup")
            logger.info("Data retention cleanup completed (keep=%ddays)", keep_days)
        except Exception as e:
            logger.warning("Data cleanup error: %s", e)

    async def _send_alerts(self, alerts: list[str]) -> None:
        """Send alerts via configured channels."""
        # Generic webhook (Discord, Slack, custom)
        webhook_url = self._get("webhook.url", "")
        if webhook_url:
            await self._send_webhook(alerts, webhook_url)

        # WebSocket broadcast to connected clients
        ws_port = self._get("websocket.port", 0)
        if ws_port:
            await self._broadcast_ws(alerts, ws_port)

    async def _send_webhook(self, alerts: list[str], url: str) -> None:
        """Send alert via generic webhook (Discord, Slack, custom).

        Supports:
        - Discord: uses 'content' field
        - Slack: uses 'text' field
        - Generic JSON POST: sends {"text": "...", "alerts": [...]}
        """
        import httpx
        text = "HLTV API Alert:\n" + "\n".join("- " + a for a in alerts)
        payload: dict[str, Any] = {
            "text": text,
            "alerts": alerts,
            "source": "hltv-api",
            "timestamp": tmod.strftime("%Y-%m-%dT%H:%M:%SZ", tmod.gmtime()),
        }
        # Discord uses 'content', Slack uses 'text'
        if "discord" in url:
            payload = {"content": text}
        elif "slack" in url:
            payload = {"text": text}

        try:
            async with httpx.AsyncClient(timeout=10) as c:
                resp = await c.post(url, json=payload)
                logger.debug("Webhook alert sent: %s", resp.status_code)
        except Exception as e:
            logger.warning("Webhook alert failed: %s", e)

    async def _broadcast_ws(self, alerts: list[str], port: int) -> None:
        """Broadcast alert to all connected WebSocket clients."""
        text = "HLTV API Alert:\n" + "\n".join("- " + a for a in alerts)
        payload = json.dumps({
            "type": "alert",
            "message": text,
            "alerts": alerts,
            "timestamp": tmod.strftime("%Y-%m-%dT%H:%M:%SZ", tmod.gmtime()),
        })
        # Broadcast to all connected WS clients via the shared store
        try:
            from src.monitor.ws import broadcast
            await broadcast(payload)
        except Exception as e:
            logger.debug("WebSocket broadcast failed: %s", e)

    def get_status(self) -> dict[str, Any]:
        """Get current monitor status.

        Returns a dict suitable for the 'hltv status' command.
        """
        status: dict[str, Any] = {
            "monitor": "running" if self._running else "stopped",
            "alerts_enabled": {
                "telegram": bool(self._get("telegram.bot_token", "")),
                "wecom": bool(self._get("wecom.webhook_url", "")),
            },
        }

        # Parse stats
        try:
            from src.utils.parsestats import report_all
            status["parse_stats"] = report_all()
        except Exception:
            pass

        # Rate limiter
        if self._client:
            try:
                status["rate_limiter"] = self._client._rate_limiter.get_stats()
            except Exception:
                pass

        # Warehouse
        if self._warehouse:
            try:
                status["warehouse"] = self._warehouse.get_stats()
            except Exception:
                pass

        return status
