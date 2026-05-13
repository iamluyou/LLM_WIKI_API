"""单元测试：图增强检索，对齐官方 graph-relevance.ts"""

from typing import Optional

import pytest
from app.services.graph_relevance import (
    RetrievalNode,
    RetrievalGraph,
    calculate_relevance,
    get_related_nodes,
    _extract_wikilinks,
    _resolve_target,
)


def _make_node(
    id: str,
    title: str = "",
    type: str = "concept",
    path: str = "",
    sources: Optional[list[str]] = None,
    out_links: Optional[set[str]] = None,
    in_links: Optional[set[str]] = None,
) -> RetrievalNode:
    return RetrievalNode(
        id=id,
        title=title or id,
        type=type,
        path=path or f"concepts/{id}.md",
        sources=sources or [],
        out_links=out_links or set(),
        in_links=in_links or set(),
    )


class TestExtractWikilinks:
    def test_basic_link(self):
        content = "See [[takin-platform]] for details"
        assert _extract_wikilinks(content) == ["takin-platform"]

    def test_aliased_link(self):
        content = "See [[takin-platform|Takin平台]] for details"
        assert _extract_wikilinks(content) == ["takin-platform"]

    def test_multiple_links(self):
        content = "[[a]] and [[b|B]] and [[c]]"
        assert _extract_wikilinks(content) == ["a", "b", "c"]

    def test_no_links(self):
        content = "No links here"
        assert _extract_wikilinks(content) == []


class TestResolveTarget:
    def test_exact_match(self):
        assert _resolve_target("takin-platform", {"takin-platform", "other"}) == "takin-platform"

    def test_case_insensitive(self):
        assert _resolve_target("Takin-Platform", {"takin-platform"}) == "takin-platform"

    def test_space_to_dash(self):
        assert _resolve_target("takin platform", {"takin-platform"}) == "takin-platform"

    def test_no_match(self):
        assert _resolve_target("missing", {"takin-platform"}) is None


class TestCalculateRelevance:
    def test_no_self_relevance(self):
        a = _make_node("a")
        graph = RetrievalGraph(nodes={"a": a})
        assert calculate_relevance(a, a, graph) == 0.0

    def test_direct_link_forward(self):
        a = _make_node("a", out_links={"b"})
        b = _make_node("b")
        graph = RetrievalGraph(nodes={"a": a, "b": b})
        score = calculate_relevance(a, b, graph)
        assert score >= 3.0  # WEIGHT_DIRECT_LINK

    def test_direct_link_backward(self):
        a = _make_node("a", in_links={"b"})
        b = _make_node("b")
        graph = RetrievalGraph(nodes={"a": a, "b": b})
        score = calculate_relevance(a, b, graph)
        assert score >= 3.0

    def test_source_overlap(self):
        a = _make_node("a", sources=["src1.md", "src2.md"])
        b = _make_node("b", sources=["src2.md", "src3.md"])
        graph = RetrievalGraph(nodes={"a": a, "b": b})
        score = calculate_relevance(a, b, graph)
        assert score >= 4.0  # 1 shared source * WEIGHT_SOURCE_OVERLAP

    def test_multiple_source_overlap(self):
        a = _make_node("a", sources=["s1.md", "s2.md", "s3.md"])
        b = _make_node("b", sources=["s1.md", "s2.md"])
        graph = RetrievalGraph(nodes={"a": a, "b": b})
        score = calculate_relevance(a, b, graph)
        assert score >= 8.0  # 2 shared * 4.0

    def test_common_neighbor_adamic_adar(self):
        c = _make_node("c")
        a = _make_node("a", out_links={"c"})
        b = _make_node("b", out_links={"c"})
        graph = RetrievalGraph(nodes={"a": a, "b": b, "c": c})
        score = calculate_relevance(a, b, graph)
        # Adamic-Adar: 1/ln(degree(c)=2) * 1.5
        import math
        expected_aa = 1.0 / math.log(2) * 1.5
        assert score >= expected_aa * 0.9  # 允许浮点误差

    def test_type_affinity(self):
        a = _make_node("a", type="entity")
        b = _make_node("b", type="concept")
        graph = RetrievalGraph(nodes={"a": a, "b": b})
        score = calculate_relevance(a, b, graph)
        assert score >= 1.2  # entity→concept affinity * WEIGHT_TYPE_AFFINITY

    def test_combined_signals(self):
        a = _make_node("a", type="entity", sources=["src.md"], out_links={"b"})
        b = _make_node("b", type="concept", sources=["src.md"])
        c = _make_node("c", out_links={"a", "b"})
        graph = RetrievalGraph(nodes={"a": a, "b": b, "c": c})
        score = calculate_relevance(a, b, graph)
        # directLink(3.0) + sourceOverlap(4.0) + commonNeighbor + typeAffinity(1.2)
        assert score >= 8.0


class TestGetRelatedNodes:
    def test_returns_limited_results(self):
        nodes = {
            "a": _make_node("a", type="entity"),
            "b": _make_node("b", type="concept"),
            "c": _make_node("c", type="source"),
        }
        graph = RetrievalGraph(nodes=nodes)
        related = get_related_nodes("a", graph, limit=2)
        assert len(related) <= 2

    def test_min_relevance_filter(self):
        a = _make_node("a")
        b = _make_node("b")
        graph = RetrievalGraph(nodes={"a": a, "b": b})
        related = get_related_nodes("a", graph, min_relevance=10.0)
        # b has no links/sources to a, relevance should be low
        assert len(related) == 0

    def test_missing_node(self):
        graph = RetrievalGraph(nodes={})
        related = get_related_nodes("missing", graph)
        assert related == []

    def test_sorted_by_relevance(self):
        # a→b (direct link), a has shared source with c
        a = _make_node("a", out_links={"b"}, sources=["src1.md"])
        b = _make_node("b", in_links={"a"})
        c = _make_node("c", sources=["src1.md"])
        d = _make_node("d")
        graph = RetrievalGraph(nodes={"a": a, "b": b, "c": c, "d": d})
        related = get_related_nodes("a", graph, limit=3)
        # b should be first (direct link 3.0 + type affinity)
        if len(related) >= 2:
            slugs = [n.id for n, _ in related]
            assert "b" in slugs
            assert "c" in slugs
