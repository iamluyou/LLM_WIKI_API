"""单元测试：向量搜索服务，对齐官方 embedding.ts"""

import os
import tempfile
import pytest
from unittest.mock import patch, AsyncMock

import numpy as np


class TestVectorDB:
    def test_upsert_and_search(self):
        from app.services.embedding import upsert_chunks, vector_search, _embedding_to_blob

        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".llm-wiki"), exist_ok=True)

            # Insert chunks for page "test-page"
            dim = 8
            vec1 = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            vec2 = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            upsert_chunks(tmpdir, "test-page", [
                {"chunk_index": 0, "chunk_text": "hello world", "heading_path": "# Intro", "embedding": vec1},
                {"chunk_index": 1, "chunk_text": "foo bar", "heading_path": "# Intro", "embedding": vec2},
            ])

            # Search with similar vector
            results = vector_search(tmpdir, vec1, top_k=10)
            assert len(results) >= 1
            assert results[0]["id"] == "test-page"
            assert results[0]["score"] > 0.5  # Cosine similarity should be high

    def test_delete_page(self):
        from app.services.embedding import upsert_chunks, delete_page, vector_search

        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".llm-wiki"), exist_ok=True)

            vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            upsert_chunks(tmpdir, "page-a", [
                {"chunk_index": 0, "chunk_text": "test", "heading_path": "", "embedding": vec},
            ])

            # Delete should work
            delete_page(tmpdir, "page-a")

            # Search should return empty
            results = vector_search(tmpdir, vec, top_k=10)
            assert len(results) == 0

    def test_count_chunks(self):
        from app.services.embedding import upsert_chunks, count_chunks

        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".llm-wiki"), exist_ok=True)

            assert count_chunks(tmpdir) == 0

            vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            upsert_chunks(tmpdir, "page-a", [
                {"chunk_index": 0, "chunk_text": "test", "heading_path": "", "embedding": vec},
                {"chunk_index": 1, "chunk_text": "test2", "heading_path": "", "embedding": vec},
            ])

            assert count_chunks(tmpdir) == 2

    def test_no_db_returns_empty(self):
        from app.services.embedding import vector_search

        with tempfile.TemporaryDirectory() as tmpdir:
            results = vector_search(tmpdir, [1.0] * 8, top_k=10)
            assert results == []


class TestFetchEmbedding:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_configured(self):
        from app.services.embedding import fetch_embedding

        with patch("app.services.embedding.settings") as mock_settings:
            mock_settings.embedding_endpoint = ""
            mock_settings.embedding_model = ""
            mock_settings.embedding_api_key = ""
            result = await fetch_embedding("test text")
            assert result is None


class TestPageLevelScoring:
    def test_max_pool_plus_tail(self):
        """对齐官方 searchByEmbedding 的 max-pool + weighted tail 算法"""
        from app.services.embedding import upsert_chunks, vector_search

        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".llm-wiki"), exist_ok=True)

            dim = 8
            # Page with two chunks: one highly relevant, one moderately
            vec_relevant = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            vec_moderate = [0.7, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            vec_other = [0.3, 0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

            # Page A: highly relevant top + moderate tail
            upsert_chunks(tmpdir, "page-a", [
                {"chunk_index": 0, "chunk_text": "highly relevant", "heading_path": "", "embedding": vec_relevant},
                {"chunk_index": 1, "chunk_text": "moderate", "heading_path": "", "embedding": vec_moderate},
            ])

            # Page B: only moderately relevant
            upsert_chunks(tmpdir, "page-b", [
                {"chunk_index": 0, "chunk_text": "other", "heading_path": "", "embedding": vec_other},
            ])

            # Query is close to vec_relevant
            results = vector_search(tmpdir, vec_relevant, top_k=10)
            assert len(results) >= 2
            # Page A should rank higher (top score + tail boost)
            assert results[0]["id"] == "page-a"
