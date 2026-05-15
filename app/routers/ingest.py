"""Ingest + 任务状态 + Embedding 管理接口"""

import logging
from typing import Optional

import httpx
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
    """执行 Ingest（Level 2 — 异步，API 版本地执行）"""
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


# --- 桌面版 Ingest 委托（方案 B） ---


class DesktopIngestRequest(BaseModel):
    source_id: Optional[str] = None


class DesktopIngestResponse(BaseModel):
    status: str  # "delegated" | "not_available" | "no_sources"
    sources: list[str]
    message: str


@router.post("/ingest/desktop", response_model=DesktopIngestResponse)
async def ingest_via_desktop(req: DesktopIngestRequest):
    """委托桌面版执行 Ingest

    通过桌面版 Clip Server 的 POST /clip 接口注入 source，
    桌面版前端自动检测并执行 ingest，进度可在桌面版 UI 查看。

    前提条件：
    - 桌面版应用已启动且打开了对应项目
    - WIKI_ROOT 与桌面版项目路径一致（共享 wiki 目录）
    - Clip Server 在 127.0.0.1:19827 运行
    """
    if not settings.desktop_ingest_enabled:
        raise HTTPException(
            status_code=400,
            detail="Desktop ingest not enabled. Set DESKTOP_INGEST_ENABLED=true in config.",
        )

    # 确定要处理的源文件
    if req.source_id:
        source_ids = [req.source_id]
    else:
        source_ids = get_uningested_sources()

    if not source_ids:
        return DesktopIngestResponse(
            status="no_sources",
            sources=[],
            message="No sources to ingest",
        )

    # 检查桌面版 Clip Server 是否可用
    clip_url = settings.desktop_clip_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{clip_url}/status")
            if resp.status_code != 200 or not resp.json().get("ok"):
                return DesktopIngestResponse(
                    status="not_available",
                    sources=source_ids,
                    message="Desktop Clip Server not available",
                )
            # 检查项目路径是否匹配
            project_resp = await client.get(f"{clip_url}/project")
            desktop_path = project_resp.json().get("path", "")
    except Exception as e:
        return DesktopIngestResponse(
            status="not_available",
            sources=source_ids,
            message=f"Desktop Clip Server unreachable: {e}",
        )

    # 逐个注入 source 到桌面版
    delegated = []
    for source_id in source_ids:
        # 读取 source 内容
        content = wiki_manager.read_file(f"raw/sources/{source_id}.md")
        if not content:
            content = wiki_manager.read_file(f"raw/sources/{source_id}")
        if not content:
            logger.warning(f"[DesktopIngest] Source not found: {source_id}")
            continue

        # 如果 source 文件已存在于共享目录，桌面版 file watcher 会自动发现
        # 直接用 /clip 接口注入（它会写入文件 + 加入 pending 队列）
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                clip_resp = await client.post(
                    f"{clip_url}/clip",
                    json={
                        "title": source_id,
                        "url": f"api://{source_id}",
                        "content": content,
                        "projectPath": settings.wiki_root,
                    },
                )
                result = clip_resp.json()
                if result.get("ok"):
                    delegated.append(source_id)
                    logger.info(f"[DesktopIngest] Delegated: {source_id} → {result.get('path', '')}")
                else:
                    logger.warning(f"[DesktopIngest] Failed for {source_id}: {result.get('error', '')}")
        except Exception as e:
            logger.error(f"[DesktopIngest] Error delegating {source_id}: {e}")

    return DesktopIngestResponse(
        status="delegated",
        sources=delegated,
        message=f"Delegated {len(delegated)}/{len(source_ids)} sources to desktop. "
                f"Watch progress in the desktop app's Activity panel. "
                f"Desktop project: {desktop_path}",
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
