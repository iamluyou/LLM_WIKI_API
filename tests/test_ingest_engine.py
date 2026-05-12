"""测试 ingest_engine — 使用 mock 隔离 LLM 调用"""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.ingest_engine import _find_raw_file, get_uningested_sources


class TestFindRawFile:
    def test_exact_match(self):
        with patch("app.services.ingest_engine.wiki_manager") as mock_wm:
            mock_wm.list_raw_sources.return_value = ["test-source.md", "other.md"]
            assert _find_raw_file("test-source.md") == "test-source.md"

    def test_stem_match(self):
        with patch("app.services.ingest_engine.wiki_manager") as mock_wm:
            mock_wm.list_raw_sources.return_value = ["test-source.md"]
            assert _find_raw_file("test-source") == "test-source.md"

    def test_partial_match(self):
        with patch("app.services.ingest_engine.wiki_manager") as mock_wm:
            mock_wm.list_raw_sources.return_value = ["my-test-source-2026.md"]
            assert _find_raw_file("test-source") == "my-test-source-2026.md"

    def test_not_found(self):
        with patch("app.services.ingest_engine.wiki_manager") as mock_wm:
            mock_wm.list_raw_sources.return_value = ["other.md"]
            assert _find_raw_file("nonexistent") is None


class TestGetUningestedSources:
    def test_finds_uningested(self):
        with patch("app.services.ingest_engine.wiki_manager") as mock_wm:
            mock_wm.list_raw_sources.return_value = ["uningested.md"]
            mock_wm.read_wiki_page.return_value = None  # 无摘要页
            result = get_uningested_sources()
            assert "uningested" in result

    def test_skips_ingested(self):
        with patch("app.services.ingest_engine.wiki_manager") as mock_wm:
            mock_wm.list_raw_sources.return_value = ["ingested.md"]
            mock_wm.read_wiki_page.return_value = "---\n---\nSummary"  # 有摘要页
            result = get_uningested_sources()
            assert len(result) == 0

    def test_empty_sources(self):
        with patch("app.services.ingest_engine.wiki_manager") as mock_wm:
            mock_wm.list_raw_sources.return_value = []
            result = get_uningested_sources()
            assert result == []


class TestRunIngest:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_llm(self):
        from app.services.ingest_engine import run_ingest
        from app.services.task_queue import Task

        with patch("app.services.ingest_engine.wiki_manager") as mock_wm, \
             patch("app.services.ingest_engine.ingest_cache") as mock_cache, \
             patch("app.services.ingest_engine.settings") as mock_settings:

            mock_wm.list_raw_sources.return_value = ["test.md"]
            mock_wm.read_file.return_value = "content"
            mock_cache.check.return_value = True
            mock_settings.ingest_cache_enabled = True

            task = Task("t1", ["test"])
            result = await run_ingest(["test"], task)

            assert result.cache_hit is True

    @pytest.mark.asyncio
    async def test_source_not_found_skipped(self):
        from app.services.ingest_engine import run_ingest
        from app.services.task_queue import Task

        with patch("app.services.ingest_engine.wiki_manager") as mock_wm:
            mock_wm.list_raw_sources.return_value = []

            task = Task("t1", ["nonexistent"])
            result = await run_ingest(["nonexistent"], task)

            assert result.pages_created == []
            assert result.pages_updated == []
