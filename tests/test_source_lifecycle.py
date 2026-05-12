"""测试 source_lifecycle — 删除 source 的完整流程"""

import os
import pytest

from app.services.source_lifecycle import (
    delete_source,
    _delete_source_impl,
    _cascade_delete_wiki_pages,
    _append_delete_log,
    SourceDeleteResult,
)
from app.services.wiki_manager import WikiManager
from app.services.wiki_cleanup import parse_frontmatter_array
from app.safety.ingest_cache import IngestCache


class TestSourceLifecycleIntegration:
    """集成测试：使用临时文件系统，直接构造 WikiManager"""

    @pytest.fixture
    def temp_wiki_env(self, tmp_path):
        """创建临时 wiki 目录结构，返回 (wiki_root, WikiManager, IngestCache)"""
        wiki_root = str(tmp_path)

        # raw/sources/
        raw_dir = os.path.join(wiki_root, "raw", "sources")
        os.makedirs(raw_dir, exist_ok=True)

        # wiki 子目录
        for subdir in ["entities", "concepts", "sources"]:
            os.makedirs(os.path.join(wiki_root, "wiki", subdir), exist_ok=True)

        # .llm-wiki/ingest-cache/
        os.makedirs(os.path.join(wiki_root, ".llm-wiki", "ingest-cache"), exist_ok=True)

        # 写入 raw source
        with open(os.path.join(raw_dir, "test-source.md"), "w") as f:
            f.write("# Test Source\n\nSome content.")

        # 写入 wiki 页面（仅来自 test-source 的页面）
        with open(os.path.join(wiki_root, "wiki", "sources", "test-source.md"), "w") as f:
            f.write("---\ntitle: Test Source\ntype: source\nsources:\n  - test-source.md\n---\nSource summary")

        # 写入 wiki 页面（来自多个 source 的共享实体页面）
        with open(os.path.join(wiki_root, "wiki", "entities", "ai.md"), "w") as f:
            f.write("---\ntitle: AI\ntype: entity\nsources:\n  - test-source.md\n  - other-source.md\n---\nAI entity content. See [[test-source]].")

        # 写入 wiki 页面（不引用 test-source 的页面）
        with open(os.path.join(wiki_root, "wiki", "concepts", "ml.md"), "w") as f:
            f.write("---\ntitle: ML\ntype: concept\nsources:\n  - other-source.md\n---\nML concept")

        # index.md
        with open(os.path.join(wiki_root, "wiki", "index.md"), "w") as f:
            f.write("# Index\n\n- [[test-source|Test Source]]\n- [[ai|AI]]\n- [[ml|ML]]\n")

        # log.md
        with open(os.path.join(wiki_root, "wiki", "log.md"), "w") as f:
            f.write("# Log\n")

        wm = WikiManager(wiki_root=wiki_root)
        cache = IngestCache(wiki_root=wiki_root)

        return wiki_root, wm, cache

    def _run_delete(self, wiki_root, wm, cache, source_id):
        """直接调用 _delete_source_impl，避免 ProjectLock 和全局单例"""
        import app.services.source_lifecycle as sl_mod

        # 临时替换全局 wiki_manager
        original_wm = sl_mod.wiki_manager
        original_cache = sl_mod.ingest_cache
        sl_mod.wiki_manager = wm
        sl_mod.ingest_cache = cache

        try:
            result = _delete_source_impl(source_id, file_already_deleted=False)
        finally:
            sl_mod.wiki_manager = original_wm
            sl_mod.ingest_cache = original_cache

        return result

    def test_delete_source_removes_raw_file(self, temp_wiki_env):
        """删除 source 后 raw 文件被移除"""
        wiki_root, wm, cache = temp_wiki_env
        result = self._run_delete(wiki_root, wm, cache, "test-source.md")

        raw_path = os.path.join(wiki_root, "raw", "sources", "test-source.md")
        assert not os.path.exists(raw_path)
        assert result.source_deleted

    def test_delete_source_removes_unique_pages(self, temp_wiki_env):
        """失去唯一来源的页面被删除"""
        wiki_root, wm, cache = temp_wiki_env
        result = self._run_delete(wiki_root, wm, cache, "test-source.md")

        # wiki/sources/test-source.md 应该被删除（唯一来源）
        source_page = os.path.join(wiki_root, "wiki", "sources", "test-source.md")
        assert not os.path.exists(source_page)
        assert "sources/test-source.md" in result.deleted_wiki_pages

    def test_delete_source_keeps_shared_pages(self, temp_wiki_env):
        """共享页面保留，但 sources 字段更新"""
        wiki_root, wm, cache = temp_wiki_env
        result = self._run_delete(wiki_root, wm, cache, "test-source.md")

        # wiki/entities/ai.md 应该保留（有其他来源）
        ai_page = os.path.join(wiki_root, "wiki", "entities", "ai.md")
        assert os.path.exists(ai_page)
        assert result.kept_shared_pages >= 1

        # sources 字段应该已更新
        content = open(ai_page).read()
        sources = parse_frontmatter_array(content, "sources")
        assert "test-source.md" not in sources
        assert "other-source.md" in sources

    def test_delete_source_cleans_index(self, temp_wiki_env):
        """index.md 中指向已删页面的条目被清理"""
        wiki_root, wm, cache = temp_wiki_env
        result = self._run_delete(wiki_root, wm, cache, "test-source.md")

        index_content = open(os.path.join(wiki_root, "wiki", "index.md")).read()
        # test-source 的条目应该被清理
        assert "[[test-source" not in index_content

    def test_delete_source_cleans_wikilinks(self, temp_wiki_env):
        """幸存页面中指向已删页面的 wikilink 被转为纯文本"""
        wiki_root, wm, cache = temp_wiki_env
        result = self._run_delete(wiki_root, wm, cache, "test-source.md")

        ai_page = os.path.join(wiki_root, "wiki", "entities", "ai.md")
        content = open(ai_page).read()
        # [[test-source]] 应该变为纯文本
        assert "[[test-source]]" not in content
        # 正文应保留 "test-source" 纯文本
        assert "test-source" in content

    def test_delete_unrelated_page_untouched(self, temp_wiki_env):
        """不引用被删 source 的页面完全不受影响"""
        wiki_root, wm, cache = temp_wiki_env
        result = self._run_delete(wiki_root, wm, cache, "test-source.md")

        ml_page = os.path.join(wiki_root, "wiki", "concepts", "ml.md")
        assert os.path.exists(ml_page)
        content = open(ml_page).read()
        assert "other-source.md" in content

    def test_delete_nonexistent_source_raises(self):
        """删除不存在的 source 抛出异常"""
        with pytest.raises(FileNotFoundError):
            delete_source("nonexistent-source.md")

    def test_delete_source_appends_log(self, temp_wiki_env):
        """删除日志被追加到 log.md"""
        wiki_root, wm, cache = temp_wiki_env
        result = self._run_delete(wiki_root, wm, cache, "test-source.md")

        log_content = open(os.path.join(wiki_root, "wiki", "log.md")).read()
        assert "delete" in log_content
        assert "test-source.md" in log_content

    def test_delete_source_invalidates_cache(self, temp_wiki_env):
        """删除 source 后缓存失效"""
        wiki_root, wm, cache = temp_wiki_env
        # 先保存一个缓存条目
        cache.save("test-source.md", "# Test Source\n\nSome content.", {"pages_created": []})
        assert cache.check("test-source.md", "# Test Source\n\nSome content.")

        # 删除
        result = self._run_delete(wiki_root, wm, cache, "test-source.md")

        # 缓存应该已失效
        assert not cache.check("test-source.md", "# Test Source\n\nSome content.")
