"""模拟测试：API 端到端集成测试（不依赖 LLM 调用）"""

import os
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.services.wiki_manager import WikiManager


@pytest.fixture
def temp_wiki(tmp_path):
    """创建临时 wiki 目录结构"""
    wiki_root = str(tmp_path / "TestWiki")
    os.makedirs(os.path.join(wiki_root, "raw", "sources"), exist_ok=True)
    os.makedirs(os.path.join(wiki_root, "wiki", "entities"), exist_ok=True)
    os.makedirs(os.path.join(wiki_root, "wiki", "concepts"), exist_ok=True)
    os.makedirs(os.path.join(wiki_root, "wiki", "sources"), exist_ok=True)

    # 写入 purpose.md
    with open(os.path.join(wiki_root, "purpose.md"), "w") as f:
        f.write("# Test Purpose\n\nTest wiki for API testing.")

    # 写入 schema.md
    with open(os.path.join(wiki_root, "schema.md"), "w") as f:
        f.write("# Wiki Schema\n\nTest schema.")

    # 写入 index.md
    with open(os.path.join(wiki_root, "wiki", "index.md"), "w") as f:
        f.write("# Index\n\n## Entities\n- [[test-entity]] — Test entity\n")

    # 写入已有 wiki 页面
    with open(os.path.join(wiki_root, "wiki", "entities", "test-entity.md"), "w") as f:
        f.write("---\ntype: entity\ntitle: Test Entity\ntags: [test]\nrelated: []\ncreated: 2026-05-12\nupdated: 2026-05-12\nsources: []\n---\n# Test Entity\n\nA test entity for unit testing.")

    # 写入 raw source
    with open(os.path.join(wiki_root, "raw", "sources", "test-source-2026-05-12.md"), "w") as f:
        f.write("# Test Source\n\nThis is a test source document about machine learning.")

    return wiki_root


@pytest.fixture
def client(temp_wiki):
    """创建 TestClient，使用临时 wiki 目录"""
    from app.config import settings
    from app.services.wiki_manager import wiki_manager as wm_instance

    # 临时替换 wiki_root
    old_root = settings.wiki_root
    old_wm_root = wm_instance.wiki_root
    old_wm_dir = wm_instance.wiki_dir
    old_wm_raw = wm_instance.raw_dir

    settings.wiki_root = temp_wiki
    wm_instance.wiki_root = temp_wiki
    wm_instance.wiki_dir = os.path.join(temp_wiki, "wiki")
    wm_instance.raw_dir = os.path.join(temp_wiki, "raw", "sources")

    from app.main import app
    test_client = TestClient(app)
    yield test_client

    # 恢复
    settings.wiki_root = old_root
    wm_instance.wiki_root = old_wm_root
    wm_instance.wiki_dir = old_wm_dir
    wm_instance.raw_dir = old_wm_raw


class TestHealthEndpoint:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestPagesAPI:
    def test_list_pages(self, client):
        response = client.get("/api/pages")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    def test_search_pages(self, client):
        response = client.get("/api/pages?keyword=test")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    def test_get_page(self, client):
        response = client.get("/api/pages/entities/test-entity")
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Entity"
        assert "test entity" in data["content"].lower()

    def test_get_page_not_found(self, client):
        response = client.get("/api/pages/entities/nonexistent")
        assert response.status_code == 404

    def test_filter_by_type(self, client):
        response = client.get("/api/pages?type=entity")
        assert response.status_code == 200
        data = response.json()
        for page in data["pages"]:
            assert page["type"] == "entity"


class TestSourcesAPI:
    def test_create_source(self, client):
        response = client.post("/api/sources", json={
            "title": "New Document",
            "content": "# New Document\n\nThis is a new document for testing.",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ingested"] is False
        assert data["size_bytes"] > 0
        assert "raw/sources/" in data["path"]

    def test_create_source_with_filename(self, client):
        response = client.post("/api/sources", json={
            "title": "Custom",
            "content": "Content",
            "filename": "custom-name.md",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "custom-name.md"


class TestStatsAPI:
    def test_get_stats(self, client):
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_pages" in data
        assert "by_type" in data
        assert data["total_pages"] >= 1


class TestGraphAPI:
    def test_get_graph(self, client):
        response = client.get("/api/graph")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) >= 1


class TestWikiManagerDirect:
    """直接测试 WikiManager 功能"""

    def test_read_purpose(self, temp_wiki):
        wm = WikiManager(temp_wiki)
        purpose = wm.read_purpose()
        assert "Test Purpose" in purpose

    def test_read_schema(self, temp_wiki):
        wm = WikiManager(temp_wiki)
        schema = wm.read_schema()
        assert "Schema" in schema

    def test_list_wiki_files(self, temp_wiki):
        wm = WikiManager(temp_wiki)
        files = wm.list_wiki_files()
        assert len(files) >= 1

    def test_list_raw_sources(self, temp_wiki):
        wm = WikiManager(temp_wiki)
        sources = wm.list_raw_sources()
        assert len(sources) >= 1

    def test_write_and_read_wiki_page(self, temp_wiki):
        wm = WikiManager(temp_wiki)
        wm.write_wiki_page("concepts/test-concept.md", "# Test Concept\n\nContent here.")
        content = wm.read_wiki_page("concepts/test-concept.md")
        assert content is not None
        assert "Test Concept" in content

    def test_write_raw_source(self, temp_wiki):
        wm = WikiManager(temp_wiki)
        path = wm.write_raw_source("new-source.md", "# New Source\n\nContent")
        assert "raw/sources/new-source.md" in path

    def test_search_pages(self, temp_wiki):
        wm = WikiManager(temp_wiki)
        pages, total = wm.search_pages(keyword="test")
        assert total >= 1

    def test_get_stats(self, temp_wiki):
        wm = WikiManager(temp_wiki)
        stats = wm.get_stats()
        assert stats["total_pages"] >= 1
        assert stats["raw_sources"] >= 1
