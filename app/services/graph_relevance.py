"""图增强检索，对齐桌面版 graph-relevance.ts

4 信号加权 1 跳扩展：directLink + sourceOverlap + Adamic-Adar + typeAffinity
"""

import logging
import math
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from app.services.wiki_manager import WikiManager

logger = logging.getLogger(__name__)

# --- 权重常量（对齐官方 WEIGHTS） ---
WEIGHT_DIRECT_LINK = 3.0
WEIGHT_SOURCE_OVERLAP = 4.0
WEIGHT_COMMON_NEIGHBOR = 1.5
WEIGHT_TYPE_AFFINITY = 1.0

# 类型亲和度矩阵（对齐官方 TYPE_AFFINITY）
TYPE_AFFINITY: dict[str, dict[str, float]] = {
    "entity": {"concept": 1.2, "entity": 0.8, "source": 1.0, "synthesis": 1.0, "query": 0.8},
    "concept": {"entity": 1.2, "concept": 0.8, "source": 1.0, "synthesis": 1.2, "query": 1.0},
    "source": {"entity": 1.0, "concept": 1.0, "source": 0.5, "query": 0.8, "synthesis": 1.0},
    "query": {"concept": 1.0, "entity": 0.8, "synthesis": 1.0, "source": 0.8, "query": 0.5},
    "synthesis": {"concept": 1.2, "entity": 1.0, "source": 1.0, "query": 1.0, "synthesis": 0.8},
}

WIKILINK_REGEX = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")


@dataclass
class RetrievalNode:
    id: str
    title: str
    type: str
    path: str  # 相对路径，如 entities/takin-platform.md
    sources: list[str] = field(default_factory=list)
    out_links: set[str] = field(default_factory=set)
    in_links: set[str] = field(default_factory=set)


@dataclass
class RetrievalGraph:
    nodes: dict[str, RetrievalNode] = field(default_factory=dict)
    data_version: int = 0


def _extract_wikilinks(content: str) -> list[str]:
    """从 markdown 内容提取 wikilink 目标"""
    return [m.group(1).strip() for m in WIKILINK_REGEX.finditer(content)]


def _resolve_target(raw: str, node_ids: set[str]) -> Optional[str]:
    """解析 wikilink 目标到实际节点 ID（对齐官方 resolveTarget）"""
    if raw in node_ids:
        return raw
    normalized = raw.lower().replace(" ", "-")
    for nid in node_ids:
        nid_lower = nid.lower()
        if nid_lower == normalized:
            return nid
        if nid_lower == raw.lower():
            return nid
        if nid_lower.replace(" ", "-") == normalized:
            return nid
    return None


def _get_neighbors(node: RetrievalNode) -> set[str]:
    return node.out_links | node.in_links


def _get_degree(node: RetrievalNode) -> int:
    return len(node.out_links) + len(node.in_links)


def calculate_relevance(
    node_a: RetrievalNode,
    node_b: RetrievalNode,
    graph: RetrievalGraph,
) -> float:
    """计算两个节点的相关性得分（对齐官方 calculateRelevance）

    4 个信号加权求和：
    1. directLink (3.0) — 双向 wikilink
    2. sourceOverlap (4.0) — frontmatter sources 共享
    3. commonNeighbor (1.5) — Adamic-Adar 共同邻居
    4. typeAffinity (1.0) — 类型亲和度矩阵
    """
    if node_a.id == node_b.id:
        return 0.0

    # Signal 1: Direct links
    forward = 1 if node_b.id in node_a.out_links else 0
    backward = 1 if node_b.id in node_a.in_links else 0
    direct_link_score = (forward + backward) * WEIGHT_DIRECT_LINK

    # Signal 2: Source overlap
    sources_a = set(node_a.sources)
    shared = sum(1 for s in node_b.sources if s in sources_a)
    source_overlap_score = shared * WEIGHT_SOURCE_OVERLAP

    # Signal 3: Common neighbors — Adamic-Adar
    neighbors_a = _get_neighbors(node_a)
    neighbors_b = _get_neighbors(node_b)
    adamic_adar = 0.0
    for neighbor_id in neighbors_a:
        if neighbor_id in neighbors_b:
            neighbor = graph.nodes.get(neighbor_id)
            if neighbor:
                degree = _get_degree(neighbor)
                adamic_adar += 1.0 / math.log(max(degree, 2))
    common_neighbor_score = adamic_adar * WEIGHT_COMMON_NEIGHBOR

    # Signal 4: Type affinity
    affinity_map = TYPE_AFFINITY.get(node_a.type, {})
    type_affinity_score = affinity_map.get(node_b.type, 0.5) * WEIGHT_TYPE_AFFINITY

    return direct_link_score + source_overlap_score + common_neighbor_score + type_affinity_score


def get_related_nodes(
    node_id: str,
    graph: RetrievalGraph,
    limit: int = 5,
    min_relevance: float = 0.0,
) -> list[tuple[RetrievalNode, float]]:
    """获取与指定节点最相关的节点列表（对齐官方 getRelatedNodes）"""
    source = graph.nodes.get(node_id)
    if not source:
        return []

    scored: list[tuple[RetrievalNode, float]] = []
    for nid, node in graph.nodes.items():
        if nid == node_id:
            continue
        relevance = calculate_relevance(source, node, graph)
        if relevance > min_relevance:
            scored.append((node, relevance))

    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------

_cached_graph: Optional[RetrievalGraph] = None
_cache_version: int = -1


def build_retrieval_graph(wm: WikiManager, data_version: int = 0) -> RetrievalGraph:
    """构建检索图（对齐官方 buildRetrievalGraph），带缓存"""
    global _cached_graph, _cache_version

    if _cached_graph is not None and _cache_version == data_version:
        return _cached_graph

    wiki_files = wm.list_wiki_files()
    raw_nodes: list[dict] = []

    # 第一遍：读取所有文件，构建原始节点数据
    # 对齐桌面版：node_id = fileName（不含目录前缀），如 "takin-platform" 而非 "entities/takin-platform"
    # 这样 [[takin-platform]] wikilink 才能匹配
    for rel_path in wiki_files:
        filename = os.path.basename(rel_path)
        node_id = filename.replace(".md", "")
        content = wm.read_wiki_page(rel_path)
        if content is None:
            continue

        fm = wm.parse_frontmatter(content)
        title = fm.get("title", "")
        if not title:
            heading_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            title = heading_match.group(1).strip() if heading_match else node_id.replace("-", " ")

        raw_nodes.append({
            "id": node_id,
            "title": title,
            "type": str(fm.get("type", "other")).lower(),
            "path": rel_path,
            "sources": fm.get("sources", []),
            "raw_links": _extract_wikilinks(content),
        })

    node_ids = {n["id"] for n in raw_nodes}

    # 第二遍：解析链接，构建双向图
    out_links: dict[str, set[str]] = {n["id"]: set() for n in raw_nodes}
    in_links: dict[str, set[str]] = {n["id"]: set() for n in raw_nodes}

    for raw in raw_nodes:
        for link_target in raw["raw_links"]:
            resolved = _resolve_target(link_target, node_ids)
            if resolved is None or resolved == raw["id"]:
                continue
            out_links[raw["id"]].add(resolved)
            in_links[resolved].add(raw["id"])

    # 构建不可变节点字典
    nodes: dict[str, RetrievalNode] = {}
    for raw in raw_nodes:
        nodes[raw["id"]] = RetrievalNode(
            id=raw["id"],
            title=raw["title"],
            type=raw["type"],
            path=raw["path"],
            sources=list(raw["sources"]),
            out_links=out_links[raw["id"]].copy(),
            in_links=in_links[raw["id"]].copy(),
        )

    graph = RetrievalGraph(nodes=nodes, data_version=data_version)
    _cached_graph = graph
    _cache_version = data_version
    logger.info(f"[Graph] Built retrieval graph: {len(nodes)} nodes")
    return graph


def clear_graph_cache() -> None:
    """清除图缓存（ingest 完成后调用）"""
    global _cached_graph, _cache_version
    _cached_graph = None
    _cache_version = -1
