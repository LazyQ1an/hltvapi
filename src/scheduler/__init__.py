"""
Task scheduler for automated HLTV data collection.

Uses APScheduler for reliable cron-style scheduling.
Runs in background alongside the FastAPI server.

Usage:
    from src.scheduler import start_scheduler, stop_scheduler

    # Start in background
    scheduler = start_scheduler(client, warehouse)

    # Shut down
    stop_scheduler(scheduler)
"""

from __future__ import annotations

from .core import start_scheduler, stop_scheduler

__all__ = ["start_scheduler", "stop_scheduler"]
