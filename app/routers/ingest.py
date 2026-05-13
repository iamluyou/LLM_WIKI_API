"""Ingest + 任务状态 + Embedding 管理接口"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.models.wiki import IngestRequest, IngestResponse, TaskStatusResponse
from app.services.ingest_engine import run_ingest, get_uningested_sources
from app.services.task_queue import task_queue
from app.services.wiki_manager import wiki_manager

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


# --- Embedding 管理接口 ---


class EmbedStatusResponse(BaseModel):
    enabled: bool
    model: str
    endpoint: str
    chunk_count: int


@router.get("/embed/status", response_model=EmbedStatusResponse)
async def get_embed_status():
    """查询 Embedding 状态"""
    from app.services.embedding import count_chunks
    return EmbedStatusResponse(
        enabled=settings.embedding_enabled,
        model=settings.embedding_model,
        endpoint=settings.embedding_endpoint,
        chunk_count=count_chunks(settings.wiki_root),
    )


class EmbedAllResponse(BaseModel):
    pages_embedded: int
    chunk_count: int


@router.post("/embed/all", response_model=EmbedAllResponse)
async def embed_all_pages():
    """批量嵌入所有 wiki 页面"""
    if not settings.embedding_enabled or not settings.embedding_model:
        raise HTTPException(
            status_code=400,
            detail="Embedding not enabled. Set EMBEDDING_ENABLED=true and EMBEDDING_MODEL in config."
        )

    from app.services.embedding import embed_all_pages, count_chunks
    count = await embed_all_pages(wiki_manager)
    return EmbedAllResponse(
        pages_embedded=count,
        chunk_count=count_chunks(settings.wiki_root),
    )
