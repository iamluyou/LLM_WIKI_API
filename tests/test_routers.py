"""测试路由层 — 使用 FastAPI TestClient + mock"""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


class TestPagesRouter:
    def test_list_pages(self):
        with patch("app.routers.pages.wiki_manager") as mock_wm:
            mock_wm.search_pages.return_value = ([], 0)
            resp = client.get("/api/pages")
            assert resp.status_code == 200
            assert resp.json()["total"] == 0

    def test_get_page_found(self):
        with patch("app.routers.pages.wiki_manager") as mock_wm:
            mock_wm.read_wiki_page.return_value = "---\ntitle: Test\ntype: entity\n---\nBody"
            mock_wm.parse_frontmatter.return_value = {"title": "Test", "type": "entity", "tags": [], "related": [], "created": "2026-01-01", "updated": "2026-01-01"}
            mock_wm.get_body.return_value = "Body"
            resp = client.get("/api/pages/entities/test")
            assert resp.status_code == 200
            assert resp.json()["title"] == "Test"

    def test_get_page_not_found(self):
        with patch("app.routers.pages.wiki_manager") as mock_wm:
            mock_wm.read_wiki_page.return_value = None
            resp = client.get("/api/pages/nonexistent")
            assert resp.status_code == 404

    def test_delete_page(self):
        with patch("app.routers.pages.wiki_manager") as mock_wm:
            mock_wm.wiki_dir = "/tmp/test-wiki"
            with patch("os.path.isfile", return_value=True), \
                 patch("os.remove"):
                resp = client.delete("/api/pages/entities/test")
                assert resp.status_code == 200
                assert resp.json()["status"] == "deleted"


class TestSourcesRouter:
    def test_create_source(self):
        with patch("app.routers.sources.wiki_manager") as mock_wm:
            mock_wm.write_raw_source.return_value = "raw/sources/test.md"
            resp = client.post("/api/sources", json={
                "title": "Test Source",
                "content": "Some content",
            })
            assert resp.status_code == 200
            assert resp.json()["filename"].endswith(".md")

    def test_create_source_with_filename(self):
        with patch("app.routers.sources.wiki_manager") as mock_wm:
            mock_wm.write_raw_source.return_value = "raw/sources/custom.md"
            resp = client.post("/api/sources", json={
                "title": "Test",
                "content": "Content",
                "filename": "custom.md",
            })
            assert resp.status_code == 200
            assert resp.json()["filename"] == "custom.md"

    def test_delete_source_success(self):
        with patch("app.routers.sources.delete_source") as mock_del:
            from app.services.source_lifecycle import SourceDeleteResult
            result = SourceDeleteResult()
            result.source_deleted = True
            result.deleted_wiki_pages = ["sources/test.md"]
            mock_del.return_value = result
            resp = client.delete("/api/sources/test-source")
            assert resp.status_code == 200
            assert resp.json()["source_deleted"] is True

    def test_delete_source_not_found(self):
        with patch("app.routers.sources.delete_source") as mock_del:
            mock_del.side_effect = FileNotFoundError("Not found")
            resp = client.delete("/api/sources/nonexistent")
            assert resp.status_code == 404


class TestIngestRouter:
    def test_ingest_with_source_id(self):
        with patch("app.routers.ingest.task_queue") as mock_tq, \
             patch("app.routers.ingest.get_uningested_sources"):
            mock_tq.submit = AsyncMock(return_value="task-1")
            resp = client.post("/api/ingest", json={"source_id": "test-source"})
            assert resp.status_code == 200
            assert resp.json()["task_id"] == "task-1"

    def test_ingest_no_sources(self):
        with patch("app.routers.ingest.get_uningested_sources", return_value=[]):
            resp = client.post("/api/ingest", json={})
            assert resp.status_code == 400

    def test_get_task_status(self):
        from app.models.wiki import TaskStatusResponse
        with patch("app.routers.ingest.task_queue") as mock_tq:
            mock_tq.get_status.return_value = TaskStatusResponse(
                task_id="task-1", status="completed"
            )
            resp = client.get("/api/tasks/task-1")
            assert resp.status_code == 200
            assert resp.json()["status"] == "completed"

    def test_get_task_not_found(self):
        with patch("app.routers.ingest.task_queue") as mock_tq:
            mock_tq.get_status.return_value = None
            resp = client.get("/api/tasks/nonexistent")
            assert resp.status_code == 404


class TestGraphRouter:
    def test_get_stats(self):
        with patch("app.routers.graph.wiki_manager") as mock_wm:
            mock_wm.get_stats.return_value = {"total_pages": 0, "by_type": {}}
            resp = client.get("/api/stats")
            assert resp.status_code == 200

    def test_get_graph(self):
        with patch("app.routers.graph.wiki_manager") as mock_wm:
            mock_wm.list_wiki_files.return_value = []
            resp = client.get("/api/graph")
            assert resp.status_code == 200
            assert resp.json()["nodes"] == []


class TestQueryRouter:
    def test_query(self):
        with patch("app.routers.query.run_query", new_callable=AsyncMock) as mock_q:
            from app.models.wiki import QueryResponse
            mock_q.return_value = QueryResponse(answer="Test answer")
            resp = client.post("/api/query", json={"question": "What is AI?"})
            assert resp.status_code == 200
            assert resp.json()["answer"] == "Test answer"


class TestHealthCheck:
    def test_health(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
