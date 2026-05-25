"""
APScheduler-based task scheduler for automated HLTV data collection.

v3.0: Adaptive load scheduling.
- Checks CPU load before running jobs (backs off if CPU > threshold)
- Configurable cron expressions from config
- Graceful shutdown
"""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("hltv.scheduler")


def _cpu_usage() -> float:
    """Get current CPU usage percentage (0-100).

    Returns 0 if unable to determine (safe default).
    """
    try:
        import psutil
        return psutil.cpu_percent(interval=0.1)
    except ImportError:
        return 0.0


def _memory_usage() -> float:
    """Get current memory usage percentage (0-100)."""
    try:
        import psutil
        return psutil.virtual_memory().percent
    except ImportError:
        return 0.0


def start_scheduler(
    client: Any,
    warehouse: Any | None = None,
    *,
    config: dict[str, Any] | None = None,
    ranking_hour: int = 6,
    ranking_minute: int = 0,
    results_hour: int = 7,
    results_minute: int = 0,
) -> AsyncIOScheduler:
    """Start background task scheduler with adaptive load.

    Args:
        client: HLTVClient instance.
        warehouse: Warehouse instance (optional).
        config: Scheduler config dict with keys:
            - enabled: bool
            - ranking_snapshot: cron expression (e.g. "0 6 * * *")
            - results_archive: cron expression
            - adaptive: bool (slow down when CPU high)
            - cpu_threshold: int (back off above this %)
        ranking_hour: Fallback hour (used if no config).
        ranking_minute: Fallback minute.
        results_hour: Fallback hour.
        results_minute: Fallback minute.

    Returns:
        Running AsyncIOScheduler instance.
    """
    cfg = config or {}
    if not cfg.get("enabled", True):
        logger.info("Scheduler disabled by config")
        scheduler = AsyncIOScheduler()
        scheduler.start()
        return scheduler

    scheduler = AsyncIOScheduler()

    # Parse cron expressions from config, with fallback to legacy params
    ranking_cron = cfg.get("ranking_snapshot", "")
    if ranking_cron and " " in ranking_cron:
        parts = ranking_cron.split()
        ranking_trigger = CronTrigger(
            minute=int(parts[0]), hour=int(parts[1]),
        )
    else:
        ranking_trigger = CronTrigger(hour=ranking_hour, minute=ranking_minute)

    results_cron = cfg.get("results_archive", "")
    if results_cron and " " in results_cron:
        parts = results_cron.split()
        results_trigger = CronTrigger(
            minute=int(parts[0]), hour=int(parts[1]),
        )
    else:
        results_trigger = CronTrigger(hour=results_hour, minute=results_minute)

    adaptive = cfg.get("adaptive", False)
    cpu_threshold = cfg.get("cpu_threshold", 70)

    scheduler.add_job(
        _save_ranking_snapshot,
        ranking_trigger,
        args=[client, warehouse, adaptive, cpu_threshold],
        id="ranking_snapshot",
        name="Daily ranking snapshot",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _save_results_archive,
        results_trigger,
        args=[client, warehouse, adaptive, cpu_threshold],
        id="results_archive",
        name="Daily results archive",
        misfire_grace_time=3600,
    )

    logger.info(
        "Scheduler started (adaptive=%s, cpu_threshold=%d%%)",
        adaptive, cpu_threshold,
    )
    scheduler.start()
    return scheduler


async def _check_load(adaptive: bool, cpu_threshold: int) -> bool:
    """Check if system load allows running a job.

    Args:
        adaptive: Whether adaptive mode is enabled.
        cpu_threshold: CPU % threshold to back off.

    Returns:
        True if should proceed, False if should skip.
    """
    if not adaptive:
        return True
    cpu = _cpu_usage()
    mem = _memory_usage()
    if cpu > cpu_threshold:
        logger.warning(
            "Load too high (CPU=%d%% > %d%%), skipping job", cpu, cpu_threshold,
        )
        return False
    if mem > 90:
        logger.warning("Memory critical (%d%%), skipping job", mem)
        return False
    logger.debug("Load OK: CPU=%d%%, MEM=%d%%", cpu, mem)
    return True


async def _save_ranking_snapshot(
    client: Any, warehouse: Any | None,
    adaptive: bool = False, cpu_threshold: int = 70,
) -> None:
    """Fetch current ranking and save to warehouse."""
    if not await _check_load(adaptive, cpu_threshold):
        return
    from src.endpoints.teams import TeamsEndpoint

    try:
        ranking = await TeamsEndpoint(client).get_ranking()
        count = len(ranking.teams) if ranking.teams else 0
        logger.info("Ranking snapshot: %d teams fetched", count)
        if warehouse and ranking:
            warehouse.save_ranking_snapshot(ranking)
            logger.info("Ranking saved to warehouse")
    except Exception as e:
        logger.error("Ranking snapshot failed: %s", e)


async def _save_results_archive(
    client: Any, warehouse: Any | None,
    adaptive: bool = False, cpu_threshold: int = 70,
) -> None:
    """Fetch recent results and save to warehouse."""
    if not await _check_load(adaptive, cpu_threshold):
        return
    from src.endpoints.matches import MatchesEndpoint

    try:
        results = await MatchesEndpoint(client).get_results(page=1)
        logger.info("Results archive: %d matches fetched", len(results))
        if warehouse and results:
            for match in results:
                warehouse.save_match(match)
            logger.info("Results saved to warehouse")
    except Exception as e:
        logger.error("Results archive failed: %s", e)


def stop_scheduler(scheduler: AsyncIOScheduler | None) -> None:
    """Gracefully stop the scheduler."""
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

