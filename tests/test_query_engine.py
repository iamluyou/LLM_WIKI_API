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
             patch("app.services.query_engine.SearchService") as mock_svc_cls:

            mock_svc = MagicMock()
            mock_svc.search.return_value = ([], 0)
            mock_svc_cls.return_value = mock_svc
            mock_llm.achat = AsyncMock(return_value=("I don't know", {"input": 5, "output": 10}))

            result = await run_query("What is X?", save_to_wiki=False)
            assert result.answer == "I don't know"

    @pytest.mark.asyncio
    async def test_query_with_search_results(self):
        from app.services.query_engine import run_query

        with patch("app.services.query_engine.wiki_manager") as mock_wm, \
             patch("app.services.query_engine.llm_client") as mock_llm, \
             patch("app.services.query_engine.SearchService") as mock_svc_cls, \
             patch("app.services.query_engine.settings") as mock_settings:

            mock_settings.output_language = "Chinese"
            mock_svc = MagicMock()
            mock_svc.search.return_value = (
                [{"slug": "ai", "title": "AI", "type": "entity", "tags": [], "related": [], "created": "", "updated": "", "content": "", "snippet": ""}],
                1,
            )
            mock_svc_cls.return_value = mock_svc

            mock_wm.read_wiki_page.return_value = "---\ntitle: AI\n---\nAI content"
            mock_wm.read_purpose.return_value = "Research"
            mock_wm.read_schema.return_value = "Schema"
            mock_llm.achat = AsyncMock(return_value=("AI is artificial intelligence", {"input": 20, "output": 30}))

            result = await run_query("What is AI?", save_to_wiki=False)
            assert "artificial intelligence" in result.answer
            assert len(result.citations) == 1
