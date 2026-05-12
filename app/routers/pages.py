"""内容检索 + 单页面接口"""

from fastapi import APIRouter, HTTPException

from app.models.wiki import PageListResponse, PageSummary
from app.services.wiki_manager import wiki_manager

router = APIRouter(prefix="/api", tags=["pages"])


@router.get("/pages", response_model=PageListResponse)
async def list_pages(
    keyword: str = "",
    type: str = "",
    tag: str = "",
    limit: int = 20,
    offset: int = 0,
):
    """内容检索（Level 1 — 无 LLM）"""
    page_type = type if type else None
    tag_filter = tag if tag else None
    pages, total = wiki_manager.search_pages(
        keyword=keyword or "",
        page_type=page_type,
        tag=tag_filter,
        limit=limit,
        offset=offset,
    )
    return PageListResponse(
        total=total,
        pages=[PageSummary(**p) for p in pages],
    )


@router.get("/pages/{slug:path}", response_model=PageSummary)
async def get_page(slug: str):
    """获取单个页面完整内容"""
    # 尝试直接路径
    content = wiki_manager.read_wiki_page(f"{slug}.md")
    if content is None:
        # 尝试加 .md 后缀搜索
        content = wiki_manager.read_wiki_page(slug)

    if content is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    fm = wiki_manager.parse_frontmatter(content)
    body = wiki_manager.get_body(content)

    return PageSummary(
        slug=slug,
        type=fm.get("type", ""),
        title=fm.get("title", slug),
        tags=fm.get("tags", []),
        related=fm.get("related", []),
        created=str(fm.get("created", "")),
        updated=str(fm.get("updated", "")),
        content=content,
        snippet=body[:200] + "..." if len(body) > 200 else body,
    )


@router.delete("/pages/{slug:path}")
async def delete_page(slug: str):
    """删除页面（仅 wiki 层）"""
    import os
    full_path = os.path.join(wiki_manager.wiki_dir, f"{slug}.md")
    if not os.path.isfile(full_path):
        full_path = os.path.join(wiki_manager.wiki_dir, slug)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    os.remove(full_path)
    return {"status": "deleted", "slug": slug}
