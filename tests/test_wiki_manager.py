"""测试 wiki_manager 文件读写操作"""

import os
import pytest

from app.services.wiki_manager import WikiManager


class TestWikiManagerIO:
    @pytest.fixture
    def wm(self, tmp_path):
        wiki_root = str(tmp_path)
        os.makedirs(os.path.join(wiki_root, "wiki"), exist_ok=True)
        os.makedirs(os.path.join(wiki_root, "raw", "sources"), exist_ok=True)
        return WikiManager(wiki_root=wiki_root)

    def test_write_and_read_file(self, wm, tmp_path):
        wm.write_file("purpose.md", "My purpose")
        content = wm.read_file("purpose.md")
        assert content == "My purpose"

    def test_read_nonexistent_file(self, wm):
        assert wm.read_file("nonexistent.md") is None

    def test_write_and_read_wiki_page(self, wm):
        os.makedirs(os.path.join(wm.wiki_dir, "entities"), exist_ok=True)
        wm.write_wiki_page("entities/ai.md", "---\ntitle: AI\n---\nContent")
        content = wm.read_wiki_page("entities/ai.md")
        assert "AI" in content

    def test_read_nonexistent_wiki_page(self, wm):
        assert wm.read_wiki_page("nonexistent.md") is None

    def test_write_raw_source(self, wm):
        actual_name, rel_path = wm.write_raw_source("test.md", "Source content")
        assert actual_name == "test.md"
        assert rel_path == os.path.join("raw", "sources", "test.md")
        assert os.path.isfile(os.path.join(wm.raw_dir, "test.md"))

    def test_append_to_file(self, wm):
        wm.write_wiki_page("log.md", "First line\n")
        wm.append_to_file("log.md", "Second line\n")
        content = wm.read_wiki_page("log.md")
        assert "First line" in content
        assert "Second line" in content

    def test_list_wiki_files(self, wm):
        os.makedirs(os.path.join(wm.wiki_dir, "entities"), exist_ok=True)
        wm.write_wiki_page("entities/ai.md", "content")
        wm.write_wiki_page("index.md", "index")
        files = wm.list_wiki_files()
        assert any("ai.md" in f for f in files)
        assert any("index.md" in f for f in files)

    def test_list_raw_sources(self, wm):
        wm.write_raw_source("source-a.md", "content")
        wm.write_raw_source("source-b.md", "content")
        sources = wm.list_raw_sources()
        assert "source-a.md" in sources
        assert "source-b.md" in sources

    def test_list_empty_wiki_dir(self, tmp_path):
        wm = WikiManager(wiki_root=str(tmp_path))
        assert wm.list_wiki_files() == []
        assert wm.list_raw_sources() == []

    def test_parse_frontmatter(self, wm):
        content = "---\ntitle: Test\ntype: entity\n---\nBody"
        fm = wm.parse_frontmatter(content)
        assert fm["title"] == "Test"
        assert fm["type"] == "entity"

    def test_get_body(self, wm):
        content = "---\ntitle: Test\n---\nBody text"
        body = wm.get_body(content)
        assert body == "Body text"

    def test_read_purpose(self, wm):
        wm.write_file("purpose.md", "Research wiki")
        assert wm.read_purpose() == "Research wiki"

    def test_read_schema(self, wm):
        wm.write_file("schema.md", "Schema rules")
        assert wm.read_schema() == "Schema rules"

    def test_get_stats(self, wm):
        os.makedirs(os.path.join(wm.wiki_dir, "entities"), exist_ok=True)
        wm.write_wiki_page("entities/ai.md", "content")
        wm.write_raw_source("source.md", "content")
        stats = wm.get_stats()
        assert stats["total_pages"] >= 1
        assert stats["raw_sources"] >= 1
