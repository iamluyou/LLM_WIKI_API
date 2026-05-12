"""存入原始资料 + 删除接口"""

import os
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.models.wiki import SourceCreateRequest, SourceCreateResponse, SourceDeleteResponse
from app.services.source_lifecycle import delete_source
from app.services.wiki_manager import wiki_manager

router = APIRouter(prefix="/api", tags=["sources"])


@router.post("/sources", response_model=SourceCreateResponse)
async def create_source(req: SourceCreateRequest):
    """存入原始资料（Level 1 — 无 LLM）"""
    # 生成文件名
    if req.filename:
        filename = req.filename
        if not filename.endswith(".md"):
            filename += ".md"
    else:
        # 基于标题生成 kebab-case 文件名
        slug = re.sub(r'[^\w\u4e00-\u9fff-]', '-', req.title).strip('-')
        slug = re.sub(r'-+', '-', slug)[:60]
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{slug}-{date_str}.md"

    # 写入
    rel_path = wiki_manager.write_raw_source(filename, req.content)

    return SourceCreateResponse(
        source_id=os.path.splitext(filename)[0],
        filename=filename,
        path=rel_path,
        size_bytes=len(req.content.encode("utf-8")),
        ingested=False,
    )


@router.delete("/sources/{source_id:path}", response_model=SourceDeleteResponse)
async def delete_source_endpoint(source_id: str):
    """删除 source 及其关联 wiki 页面，对齐桌面版级联删除

    流程：
    1. 删除 raw source 文件
    2. 清理 ingest cache
    3. 扫描所有 wiki 页面，决策每个页面的命运（skip/keep/delete）
    4. 级联删除失去唯一来源的页面
    5. 清理幸存页面中的引用（wikilink / related / index 条目）
    6. 追加删除日志
    """
    try:
        result = delete_source(source_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

    return SourceDeleteResponse(
        source_id=source_id,
        source_deleted=result.source_deleted,
        deleted_wiki_pages=result.deleted_wiki_pages,
        rewritten_pages=result.rewritten_pages,
        kept_shared_pages=result.kept_shared_pages,
    )
