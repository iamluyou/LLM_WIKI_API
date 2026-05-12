"""Ingest + 任务状态接口"""

from fastapi import APIRouter, HTTPException

from app.models.wiki import IngestRequest, IngestResponse, TaskStatusResponse
from app.services.ingest_engine import run_ingest, get_uningested_sources
from app.services.task_queue import task_queue

router = APIRouter(prefix="/api", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_sources(req: IngestRequest):
    """执行 Ingest（Level 2 — 异步）"""
    # 确定要处理的源文件
    if req.source_id:
        source_ids = [req.source_id]
    else:
        source_ids = get_uningested_sources()

    if not source_ids:
        raise HTTPException(status_code=400, detail="No sources to ingest")

    # 提交到任务队列
    task_id = await task_queue.submit(source_ids, run_ingest)

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
