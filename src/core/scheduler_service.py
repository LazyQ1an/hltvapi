"""
SchedulerService — 整合 APScheduler（定时任务）与 TaskOrchestrator（实时任务）。

定时任务（cron-based）：
- 06:00 ranking snapshot
- 07:00 results archive
- 每小时 upcoming/news 刷新

实时任务（event-driven）：
- Live match polling
- API/CLI 触发的即时抓取
"""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("hltv.core.scheduler_service")


class SchedulerService:
    """
    定时 + 实时任务整合服务。

    用法：
        service = SchedulerService(client, warehouse, orchestrator)
        service.start()
    """

    def __init__(
        self,
        client: Any = None,
        warehouse: Any = None,
        orchestrator: Any = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._warehouse = warehouse
        self._orchestrator = orchestrator
        self._config = config or {}
        self._apscheduler = AsyncIOScheduler()
        self._jobs: dict[str, Any] = {}

    def start(self) -> None:
        """启动所有定时任务。"""
        cfg = self._config
        if not cfg.get("enabled", True):
            logger.info("Scheduler disabled by config")
            self._apscheduler.start()
            return

        # ranking snapshot (06:00 daily)
        if cfg.get("ranking_snapshot", True):
            hour = cfg.get("ranking_hour", 6)
            minute = cfg.get("ranking_minute", 0)
            self._jobs["ranking"] = self._apscheduler.add_job(
                self._run_ranking_snapshot,
                CronTrigger(hour=hour, minute=minute),
                id="ranking_snapshot",
                misfire_grace_time=3600,
            )

        # results archive (07:00 daily)
        if cfg.get("results_archive", True):
            hour = cfg.get("results_hour", 7)
            minute = cfg.get("results_minute", 0)
            self._jobs["results"] = self._apscheduler.add_job(
                self._run_results_archive,
                CronTrigger(hour=hour, minute=minute),
                id="results_archive",
                misfire_grace_time=3600,
            )

        # upcoming refresh (every 30 min during active hours)
        if cfg.get("upcoming_refresh", True):
            self._jobs["upcoming"] = self._apscheduler.add_job(
                self._run_upcoming_refresh,
                CronTrigger(minute="0,30", hour="8-23"),
                id="upcoming_refresh",
                misfire_grace_time=600,
            )

        self._apscheduler.start()
        logger.info(
            "SchedulerService started (%d jobs)",
            len(self._jobs),
        )

    def stop(self) -> None:
        """停止所有定时任务。"""
        self._apscheduler.shutdown(wait=False)
        logger.info("SchedulerService stopped")

    async def _run_ranking_snapshot(self) -> None:
        """定时进行 ranking snapshot。"""
        logger.info("Running scheduled ranking snapshot")
        if self._orchestrator and hasattr(self._orchestrator, "schedule"):
            from .orchestrator import Task, TaskType
            self._orchestrator.schedule(Task(
                task_type=TaskType.ARCHIVE,
                priority=30,
                metadata={"action": "ranking_snapshot"},
            ))

    async def _run_results_archive(self) -> None:
        """定时归档比赛结果。"""
        logger.info("Running scheduled results archive")
        if self._orchestrator and hasattr(self._orchestrator, "schedule"):
            from .orchestrator import Task, TaskType
            self._orchestrator.schedule(Task(
                task_type=TaskType.ARCHIVE,
                priority=30,
                metadata={"action": "results_archive"},
            ))

    async def _run_upcoming_refresh(self) -> None:
        """刷新 upcoming 页面缓存。"""
        if self._client and hasattr(self._client, "get"):
            from .pipeline import FetchRequest
            try:
                if hasattr(self._client, "_pipeline"):
                    await self._client._pipeline.execute(FetchRequest(
                        url="https://www.hltv.org/matches",
                        bypass_cache=True,
                        priority=60,
                    ))
            except Exception as e:
                logger.debug("Upcoming refresh: %s", e)
