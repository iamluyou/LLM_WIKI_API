"""知识图谱 + 统计接口"""

import os
import re
from typing import Any

from fastapi import APIRouter

from app.services.wiki_manager import wiki_manager

router = APIRouter(prefix="/api", tags=["auxiliary"])


@router.get("/stats")
async def get_stats():
    """Wiki 统计信息"""
    return wiki_manager.get_stats()


@router.get("/graph")
async def get_graph():
    """获取知识图谱数据（节点 + 边）"""
    nodes = []
    edges = []
    seen_nodes = set()

    wiki_files = wiki_manager.list_wiki_files()
    for rel_path in wiki_files:
        content = wiki_manager.read_wiki_page(rel_path)
        if not content:
            continue

        fm = wiki_manager.parse_frontmatter(content)
        slug = os.path.splitext(rel_path)[0]
        title = fm.get("title", slug)
        page_type = fm.get("type", "unknown")

        # 节点
        if slug not in seen_nodes:
            nodes.append({
                "id": slug,
                "label": title,
                "type": page_type,
            })
            seen_nodes.add(slug)

        # 边：从 related 字段
        for related in fm.get("related", []):
            if related not in seen_nodes:
                nodes.append({
                    "id": related,
                    "label": related,
                    "type": "unknown",
                })
                seen_nodes.add(related)
            edges.append({"source": slug, "target": related})

        # 边：从 [[wikilinks]]
        wikilinks = re.findall(r'\[\[([^\]]+)\]\]', content)
        for link in wikilinks:
            link_slug = link.split("|")[0].strip()
            if link_slug not in seen_nodes:
                nodes.append({
                    "id": link_slug,
                    "label": link_slug,
                    "type": "unknown",
                })
                seen_nodes.add(link_slug)
            edges.append({"source": slug, "target": link_slug, "type": "wikilink"})

    return {"nodes": nodes, "edges": edges}
