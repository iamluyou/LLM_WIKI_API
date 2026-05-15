"""异步任务队列，串行执行 Ingest 任务，任务状态持久化到文件"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from app.models.wiki import TaskResult, TaskStatusResponse

logger = logging.getLogger(__name__)

# Worker 级超时：30 分钟（对齐桌面版 backstop timeout）
_WORKER_TIMEOUT = 1800


class Task:
    def __init__(self, task_id: str, source_ids: list[str]):
        self.task_id = task_id
        self.source_ids = source_ids
        self.status = "pending"
        self.progress = ""
        self.result: Optional[TaskResult] = None
        self.created_at = datetime.now()
        self._on_progress = None  # 由 TaskQueue._worker 设置

    def update_progress(self, progress: str):
        """更新进度并触发持久化"""
        self.progress = progress
        if self._on_progress:
            self._on_progress()

    def to_dict(self) -> dict:
        d = {
            "task_id": self.task_id,
            "source_ids": self.source_ids,
            "status": self.status,
            "progress": self.progress,
            "created_at": self.created_at.isoformat(),
        }
        if self.result:
            d["result"] = self.result.model_dump()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        task = cls(d["task_id"], d["source_ids"])
        task.status = d.get("status", "pending")
        task.progress = d.get("progress", "")
        task.created_at = datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.now()
        if d.get("result"):
            task.result = TaskResult(**d["result"])
        return task


class TaskQueue:
    """串行任务队列，任务状态持久化到 JSON 文件，重启后可恢复"""

    def __init__(self, concurrency: int = 1):
        self.concurrency = concurrency
        self._tasks: dict[str, Task] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._persist_path: Optional[str] = None
        self._stale_pending: list[Task] = []

    def _get_persist_path(self) -> str:
        if self._persist_path:
            return self._persist_path
        from app.config import settings
        self._persist_path = os.path.join(settings.llm_wiki_meta_dir, "tasks.json")
        return self._persist_path

    def _persist(self):
        """将所有任务状态写入文件"""
        path = self._get_persist_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = {tid: t.to_dict() for tid, t in self._tasks.items()}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[TaskQueue] Failed to persist tasks: {e}")

    def _restore(self):
        """从文件恢复任务状态"""
        path = self._get_persist_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stale_pending = []
            for tid, td in data.items():
                task = Task.from_dict(td)
                # 重启后，processing 状态的任务标记为 failed（中断丢失）
                if task.status == "processing":
                    task.status = "failed"
                    task.progress = "Server restarted during processing"
                self._tasks[tid] = task
                # 收集 pending 任务，稍后重新入队
                if task.status == "pending":
                    stale_pending.append(task)
            if self._tasks:
                logger.info(f"[TaskQueue] Restored {len(self._tasks)} task(s) from disk, {len(stale_pending)} pending to re-queue")
            # 重新入队 pending 任务（processor 在 submit 时由调用方提供，恢复时需从外部注入）
            self._stale_pending = stale_pending
        except Exception as e:
            logger.warning(f"[TaskQueue] Failed to restore tasks: {e}")
            self._stale_pending = []

    async def start(self):
        """启动后台 worker，并从磁盘恢复任务"""
        if not self._running:
            self._restore()
            self._running = True
            self._worker_task = asyncio.create_task(self._worker())
            # 重新入队重启前遗留的 pending 任务
            if self._stale_pending:
                from app.services.ingest_engine import run_ingest
                for task in self._stale_pending:
                    await self._queue.put((task, run_ingest))
                    logger.info(f"[TaskQueue] Re-queued stale pending task: {task.task_id}")
                self._stale_pending = []

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
        self._persist()
        await self._queue.put((task, processor))
        logger.info(f"[TaskQueue] Task submitted: {task_id}, sources={source_ids}, queue_size={self._queue.qsize()}")
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
            task._on_progress = self._persist
            self._persist()
            logger.info(f"[TaskQueue] Task {task.task_id} started processing")
            try:
                result = await asyncio.wait_for(
                    processor(task.source_ids, task),
                    timeout=_WORKER_TIMEOUT,
                )
                task.status = "completed"
                task.progress = "done"
                task.result = result
                self._persist()
                logger.info(f"[TaskQueue] Task {task.task_id} completed successfully")
            except asyncio.TimeoutError:
                logger.error(f"[TaskQueue] Task {task.task_id} timed out after {_WORKER_TIMEOUT}s")
                task.status = "failed"
                task.progress = f"Task timed out after {_WORKER_TIMEOUT}s"
                self._persist()
            except Exception as e:
                logger.error(f"[TaskQueue] Task {task.task_id} failed: {e}")
                task.status = "failed"
                task.progress = str(e)
                self._persist()

    def list_tasks(self) -> list[TaskStatusResponse]:
        """列出所有任务"""
        return [self.get_status(tid) for tid in self._tasks]


# 单例
task_queue = TaskQueue()
