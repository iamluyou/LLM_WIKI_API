"""测试 query_engine — 使用 mock 隔离 LLM 调用"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.models.wiki import QueryResponse, Citation


class TestRunQuery:
    @pytest.mark.asyncio
    async def test_direct_answer_when_no_results(self):
        from app.services.query_engine import run_query

        with patch("app.services.query_engine.wiki_manager") as mock_wm, \
             patch("app.services.query_engine.llm_client") as mock_llm, \
             patch("app.services.query_engine.SearchService") as mock_svc_cls, \
             patch("app.services.query_engine.build_retrieval_graph") as mock_graph:

            mock_svc = MagicMock()
            mock_svc.search.return_value = ([], 0)
            mock_svc_cls.return_value = mock_svc
            mock_llm.achat = AsyncMock(return_value=("I don't know", {"input": 5, "output": 10}))

            result = await run_query("What is X?", save_to_wiki=False)
            assert result.answer == "I don't know"

    @pytest.mark.asyncio
    async def test_greeting_shortcut(self):
        from app.services.query_engine import run_query

        with patch("app.services.query_engine.wiki_manager") as mock_wm, \
             patch("app.services.query_engine.llm_client") as mock_llm:

            mock_llm.achat = AsyncMock(return_value=("Hello!", {"input": 5, "output": 5}))
            result = await run_query("你好", save_to_wiki=False)
            # Should skip retrieval and go to direct answer
            assert result.answer == "Hello!"

    @pytest.mark.asyncio
    async def test_query_with_search_results(self):
        from app.services.query_engine import run_query
        from app.services.graph_relevance import RetrievalGraph

        empty_graph = RetrievalGraph(nodes={}, data_version=0)

        with patch("app.services.query_engine.wiki_manager") as mock_wm, \
             patch("app.services.query_engine.llm_client") as mock_llm, \
             patch("app.services.query_engine.SearchService") as mock_svc_cls, \
             patch("app.services.query_engine.build_retrieval_graph", return_value=empty_graph) as mock_graph, \
             patch("app.services.query_engine.settings") as mock_settings:

            mock_settings.llm_max_context = 204800
            mock_settings.output_language = "Chinese"
            mock_svc = MagicMock()
            mock_svc.search.return_value = (
                [{"slug": "ai", "title": "AI", "type": "entity", "tags": [], "related": [], "created": "", "updated": "", "content": "", "snippet": "", "title_match": True}],
                1,
            )
            mock_svc_cls.return_value = mock_svc

            mock_wm.read_wiki_page.return_value = "---\ntitle: AI\n---\nAI content"
            mock_wm.read_purpose.return_value = "Research"
            mock_wm.read_index.return_value = "## Index\n- AI"
            mock_llm.achat = AsyncMock(return_value=("AI is artificial intelligence <!-- cited: 1 -->", {"input": 20, "output": 30}))

            result = await run_query("What is AI?", save_to_wiki=False)
            assert "artificial intelligence" in result.answer
            assert len(result.citations) >= 1


class TestExtractCitations:
    def test_cited_comment(self):
        from app.services.query_engine import _extract_citations
        pages = [
            {"slug": "a", "title": "A", "path": "a.md"},
            {"slug": "b", "title": "B", "path": "b.md"},
            {"slug": "c", "title": "C", "path": "c.md"},
        ]
        answer = "Some text [1] and [3] <!-- cited: 1, 3 -->"
        citations = _extract_citations(answer, pages)
        assert len(citations) == 2
        assert citations[0].slug == "a"
        assert citations[1].slug == "c"

    def test_bracket_numbers_fallback(self):
        from app.services.query_engine import _extract_citations
        pages = [
            {"slug": "a", "title": "A", "path": "a.md"},
            {"slug": "b", "title": "B", "path": "b.md"},
        ]
        answer = "Some text [1] and [2]"
        citations = _extract_citations(answer, pages)
        assert len(citations) == 2

    def test_wikilink_fallback(self):
        from app.services.query_engine import _extract_citations
        pages = [
            {"slug": "takin-platform", "title": "Takin", "path": "entities/takin-platform.md"},
        ]
        answer = "See [[takin-platform]] for details"
        citations = _extract_citations(answer, pages)
        assert len(citations) == 1
        assert citations[0].slug == "takin-platform"


class TestTrimIndex:
    def test_short_index_unchanged(self):
        from app.services.query_engine import _trim_index
        index = "## Entities\n- AI\n- ML"
        result = _trim_index(index, "AI", 1000)
        assert result == index

    def test_long_index_trimmed(self):
        from app.services.query_engine import _trim_index
        index = "## Entities\n" + "\n".join(f"- Item{i}" for i in range(100))
        result = _trim_index(index, "Item5", 50)
        assert len(result) < len(index)
        assert "Item5" in result

    def test_empty_index(self):
        from app.services.query_engine import _trim_index
        assert _trim_index("", "test", 100) == ""


class TestIsGreeting:
    def test_chinese_greeting(self):
        from app.services.query_engine import _is_greeting
        assert _is_greeting("你好") is True

    def test_english_greeting(self):
        from app.services.query_engine import _is_greeting
        assert _is_greeting("hi") is True

    def test_not_greeting(self):
        from app.services.query_engine import _is_greeting
        assert _is_greeting("什么是RAG") is False
        assert _is_greeting("how does AI work") is False
