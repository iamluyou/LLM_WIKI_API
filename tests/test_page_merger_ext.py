"""测试 page_merger 三层合并逻辑"""

import pytest
from app.services.page_merger import (
    _union_arrays,
    merge_frontmatter_arrays,
    merge_page_content,
    _rebuild_page,
    backup_page,
)


class TestUnionArrays:
    def test_merge_no_duplicates(self):
        result = _union_arrays(["a", "b"], ["c", "d"])
        assert result == ["a", "b", "c", "d"]

    def test_merge_with_duplicates(self):
        result = _union_arrays(["a", "b"], ["b", "c"])
        assert result == ["a", "b", "c"]

    def test_case_insensitive_dedup(self):
        result = _union_arrays(["Test.md"], ["test.md"])
        assert len(result) == 1

    def test_empty_arrays(self):
        result = _union_arrays([], [])
        assert result == []

    def test_preserves_order(self):
        result = _union_arrays(["a", "c"], ["b"])
        assert result == ["a", "c", "b"]


class TestMergeFrontmatterArrays:
    def test_union_sources(self):
        existing = {"sources": ["a.md"], "tags": ["ai"]}
        incoming = {"sources": ["b.md"], "tags": ["ml"]}
        merged = merge_frontmatter_arrays(existing, incoming)
        assert "a.md" in merged["sources"]
        assert "b.md" in merged["sources"]
        assert "ai" in merged["tags"]
        assert "ml" in merged["tags"]

    def test_incoming_base(self):
        existing = {"title": "Old", "sources": ["a.md"]}
        incoming = {"title": "New", "sources": ["b.md"]}
        merged = merge_frontmatter_arrays(existing, incoming)
        assert merged["title"] == "New"  # incoming 为基础


class TestMergePageContent:
    def test_new_page(self):
        new = "---\ntitle: Test\ntype: entity\n---\nBody"
        result, was_llm = merge_page_content(new, None)
        assert "Body" in result
        assert was_llm is False

    def test_identical_content(self):
        content = "---\ntitle: Test\n---\nBody"
        result, was_llm = merge_page_content(content, content)
        assert result == content
        assert was_llm is False

    def test_body_same_frontmatter_diff(self):
        existing = "---\ntitle: Old\nsources: [a.md]\n---\nSame body"
        new = "---\ntitle: New\nsources: [b.md]\n---\nSame body"
        result, was_llm = merge_page_content(new, existing)
        assert "a.md" in result
        assert "b.md" in result
        assert was_llm is False

    def test_with_merger_fn(self):
        existing = "---\ntitle: Test\nsources: [a.md]\n---\nOld body"
        new = "---\ntitle: Test\nsources: [b.md]\n---\nNew body"

        def mock_merger(ex, nw, src):
            return "---\ntitle: Test\nsources: [c.md]\n---\nMerged body"

        result, was_llm = merge_page_content(new, existing, merger_fn=mock_merger)
        assert "Merged body" in result
        assert was_llm is True
        # Union 再次合并（防止 LLM 遗漏）
        assert "a.md" in result or "b.md" in result

    def test_merger_fn_failure_fallback(self):
        existing = "---\ntitle: Test\nsources: [a.md]\n---\nOld body"
        new = "---\ntitle: Test\nsources: [b.md]\n---\nNew body"

        def failing_merger(ex, nw, src):
            raise Exception("LLM failed")

        result, was_llm = merge_page_content(new, existing, merger_fn=failing_merger)
        assert "New body" in result
        assert was_llm is False

    def test_locked_fields_preserved(self):
        """locked fields (type, title, created) 在 LLM 合并路径后强制回写 existing 的值"""
        existing = "---\ntitle: Old Title\ntype: entity\ncreated: 2026-01-01\n---\nOld body"
        new = "---\ntitle: New Title\ntype: concept\ncreated: 2026-06-01\n---\nNew body"

        def mock_merger(ex, nw, src):
            return "---\ntitle: Merged\ntype: concept\ncreated: 2026-06-01\n---\nMerged body"

        result, was_llm = merge_page_content(new, existing, merger_fn=mock_merger)
        assert was_llm is True
        # locked fields 强制回写 existing 的值
        assert "Old Title" in result
        assert "entity" in result


class TestRebuildPage:
    def test_basic_rebuild(self):
        fm = {"title": "Test", "type": "entity", "tags": ["ai"]}
        body = "Content"
        result = _rebuild_page(fm, body)
        assert "---" in result
        assert "title: Test" in result
        assert "Content" in result

    def test_list_values(self):
        fm = {"tags": ["ai", "ml"]}
        result = _rebuild_page(fm, "body")
        assert "tags: [ai, ml]" in result


class TestBackupPage:
    def test_backup_creates_file(self, tmp_path):
        import os
        wiki_root = str(tmp_path)
        os.makedirs(os.path.join(wiki_root, ".llm-wiki", "page-history"), exist_ok=True)

        backup_page(wiki_root, "entities/test.md", "original content")

        # 检查备份文件存在
        backup_dir = os.path.join(wiki_root, ".llm-wiki", "page-history")
        files = os.listdir(backup_dir)
        assert len(files) == 1
        assert "entities_test.md" in files[0]

    def test_backup_best_effort(self, tmp_path):
        """备份失败不抛异常"""
        # 使用无效路径
        backup_page("/nonexistent/path", "test.md", "content")  # 不应抛异常
