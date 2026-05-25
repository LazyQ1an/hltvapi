"""
Task Orchestrator：统一的任务调度引擎。

职责：
- 管理 Fetch / Poll / Archive / Reparse / Notify 类型任务
- 优先级队列（live match > upcoming > results > ranking）
- URL-level 去重
- 自适应周期调整
- 全局并发控制
"""

from __future__ import annotations

import asyncio
import logging
import time as tmod
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from cachetools import TTLCache

logger = logging.getLogger("hltv.core.orchestrator")


class TaskType(Enum):
    FETCH = "fetch"
    POLL = "poll"
    ARCHIVE = "archive"
    REPARSE = "reparse"
    NOTIFY = "notify"


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_type: TaskType = TaskType.FETCH
    url: str | None = None
    priority: int = 0
    interval: float = 0.0
    max_retries: int = 3
    retry_count: int = 0
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = 0.0
    last_run: float | None = None
    callback: Callable | None = None
    metadata: dict = field(default_factory=dict)


_TASK_PRIORITY_MAP = {
    TaskType.POLL: 100,       # live match 最高
    TaskType.FETCH: 50,       # 按需抓取
    TaskType.NOTIFY: 40,
    TaskType.ARCHIVE: 30,     # ranking snapshot
    TaskType.REPARSE: 10,     # 后台重解析
}


class TaskOrchestrator:
    """
    统一调度引擎。

    使用 asyncio.PriorityQueue 实现优先级调度。
    每个 task 被包装为 _TaskWrapper 加入队列。

    用法：
        orch = TaskOrchestrator(max_concurrency=5)
        await orch.start()
        orch.schedule(Task(url="...", priority=100))
    """

    def __init__(
        self,
        max_concurrency: int = 5,
        fetch_pipeline: Any = None,
    ) -> None:
        self._max_concurrency = max_concurrency
        self._pipeline = fetch_pipeline
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._running: dict[str, asyncio.Task] = {}
        self._completed: dict[str, Task] = {}
        self._semaphore = asyncio.Semaphore(max_concurrency)

        # URL 去重 (5s TTL)
        self._dedup: TTLCache[str, float] = TTLCache(maxsize=500, ttl=5)

        self._worker_task: asyncio.Task | None = None
        self._running_flag = False

    def schedule(self, task: Task) -> str:
        """添加任务到队列。"""
        if task.task_type == TaskType.FETCH and task.url:
            if task.url in self._dedup:
                logger.debug("Dedup: skipping %s", task.url)
                return task.id
            self._dedup[task.url] = tmod.time()

        task.created_at = tmod.time()
        if task.priority == 0:
            task.priority = _TASK_PRIORITY_MAP.get(task.task_type, 50)

        # 优先级取负因为 PriorityQueue 取最小值
        self._queue.put_nowait((
            -task.priority,
            task.created_at,
            task,
        ))
        logger.debug("Task scheduled: %s (priority=%d)", task.id, task.priority)
        return task.id

    def cancel(self, task_id: str) -> bool:
        """取消一个正在运行或等待的任务。"""
        if task_id in self._running:
            self._running[task_id].cancel()
            del self._running[task_id]
            return True
        return False

    async def start(self) -> None:
        """启动调度器主循环。"""
        if self._running_flag:
            return
        self._running_flag = True
        self._worker_task = asyncio.create_task(self._run_loop())
        logger.info("TaskOrchestrator started (max_concurrency=%d)", self._max_concurrency)

    async def stop(self) -> None:
        """停止调度器。"""
        self._running_flag = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        # 取消所有运行中的任务
        for tid, t in list(self._running.items()):
            t.cancel()
        self._running.clear()

    async def _run_loop(self) -> None:
        """主循环：从队列取任务并执行。"""
        while self._running_flag:
            try:
                _, _, task = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Queue get error: %s", e)
                await asyncio.sleep(0.1)
                continue

            # 并发控制
            async with self._semaphore:
                worker = asyncio.create_task(self._execute(task))
                self._running[task.id] = worker
                try:
                    await worker
                except asyncio.CancelledError:
                    task.status = TaskStatus.CANCELLED
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    logger.error("Task %s failed: %s", task.id, e)
                finally:
                    self._running.pop(task.id, None)
                    self._completed[task.id] = task

            # Poll 类型任务重新入队
            if task.task_type == TaskType.POLL and task.status != TaskStatus.CANCELLED:
                task.last_run = tmod.time()
                interval = self._adaptive_interval(task)
                asyncio.create_task(self._reschedule_poll(task, interval))

    async def _execute(self, task: Task) -> None:
        """执行一个任务。"""
        task.status = TaskStatus.RUNNING
        task.last_run = tmod.time()

        if task.task_type == TaskType.FETCH and self._pipeline and task.url:
            from .pipeline import FetchRequest
            request = FetchRequest(
                url=task.url,
                priority=task.priority,
                metadata=task.metadata,
            )
            response = await self._pipeline.execute(request)
            if task.callback:
                await task.callback(response)
            task.status = TaskStatus.COMPLETED

        elif task.task_type == TaskType.POLL and task.url:
            if self._pipeline:
                from .pipeline import FetchRequest
                request = FetchRequest(
                    url=task.url,
                    bypass_cache=True,
                    priority=task.priority,
                    metadata=task.metadata,
                )
                response = await self._pipeline.execute(request)
                if task.callback:
                    await task.callback(response)
            task.status = TaskStatus.COMPLETED

        else:
            if task.callback:
                await task.callback(task)
            task.status = TaskStatus.COMPLETED

    def _adaptive_interval(self, task: Task) -> float:
        """根据上次执行情况动态调整 polling 间隔。"""
        base = task.interval or 30.0
        if task.retry_count > 0:
            return base * min(2.0 ** task.retry_count, 8.0)
        return base

    async def _reschedule_poll(self, task: Task, interval: float) -> None:
        """延迟后将 poll 任务重新入队。"""
        await asyncio.sleep(interval)
        if self._running_flag:
            new_task = Task(
                task_type=TaskType.POLL,
                url=task.url,
                priority=task.priority,
                interval=task.interval,
                max_retries=task.max_retries,
                callback=task.callback,
                metadata=task.metadata,
            )
            self.schedule(new_task)

    def get_status(self) -> dict[str, Any]:
        return {
            "queue_size": self._queue.qsize(),
            "running": len(self._running),
            "completed": len(self._completed),
            "max_concurrency": self._max_concurrency,
        }
