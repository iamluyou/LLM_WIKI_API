"""Ingest + 任务状态接口"""

import logging

from fastapi import APIRouter, HTTPException

from app.models.wiki import IngestRequest, IngestResponse, TaskStatusResponse
from app.services.ingest_engine import run_ingest, get_uningested_sources
from app.services.task_queue import task_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_sources(req: IngestRequest):
    """执行 Ingest（Level 2 — 异步）"""
    logger.info(f"[API] POST /api/ingest — source_id={req.source_id!r}")
    # 确定要处理的源文件
    if req.source_id:
        source_ids = [req.source_id]
    else:
        source_ids = get_uningested_sources()

    if not source_ids:
        logger.warning(f"[API] POST /api/ingest — no sources to ingest")
        raise HTTPException(status_code=400, detail="No sources to ingest")

    # 提交到任务队列
    task_id = await task_queue.submit(source_ids, run_ingest)
    logger.info(f"[API] Ingest task submitted: {task_id} for sources={source_ids}")

    return IngestResponse(
        task_id=task_id,
        status="processing",
        sources=source_ids,
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """查询任务状态"""
    status = task_queue.get_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return status
