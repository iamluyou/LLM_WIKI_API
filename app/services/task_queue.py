"""异步任务队列，串行执行 Ingest 任务"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.models.wiki import TaskResult, TaskStatusResponse

logger = logging.getLogger(__name__)


class Task:
    def __init__(self, task_id: str, source_ids: list[str]):
        self.task_id = task_id
        self.source_ids = source_ids
        self.status = "pending"
        self.progress = ""
        self.result: Optional[TaskResult] = None
        self.created_at = datetime.now()


class TaskQueue:
    """串行任务队列，对齐桌面版的串行 Ingest 设计"""

    def __init__(self, concurrency: int = 1):
        self.concurrency = concurrency
        self._tasks: dict[str, Task] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动后台 worker"""
        if not self._running:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker())

    async def stop(self):
        """停止后台 worker"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def submit(self, source_ids: list[str], processor) -> str:
        """提交任务，返回 task_id"""
        task_id = f"task-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
        task = Task(task_id, source_ids)
        self._tasks[task_id] = task
        await self._queue.put((task, processor))
        return task_id

    def get_status(self, task_id: str) -> Optional[TaskStatusResponse]:
        """查询任务状态"""
        task = self._tasks.get(task_id)
        if not task:
            return None
        return TaskStatusResponse(
            task_id=task.task_id,
            status=task.status,
            progress=task.progress,
            result=task.result,
        )

    async def _worker(self):
        """后台 worker，串行处理任务"""
        while self._running:
            try:
                task, processor = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            task.status = "processing"
            task.progress = "starting"
            try:
                result = await processor(task.source_ids, task)
                task.status = "completed"
                task.progress = "done"
                task.result = result
            except Exception as e:
                logger.error(f"Task {task.task_id} failed: {e}")
                task.status = "failed"
                task.progress = str(e)

    def list_tasks(self) -> list[TaskStatusResponse]:
        """列出所有任务"""
        return [self.get_status(tid) for tid in self._tasks]


# 单例
task_queue = TaskQueue()
