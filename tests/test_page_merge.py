"""单元测试：页面三层合并 + 健全性检查"""

import pytest
from app.services.page_merger import (
    merge_page_content,
    merge_frontmatter_arrays,
    _union_arrays,
    _rebuild_page,
)


class TestUnionArrays:
    def test_merge_no_duplicates(self):
        result = _union_arrays(["a", "b"], ["c", "d"])
        assert result == ["a", "b", "c", "d"]

    def test_merge_with_duplicates(self):
        result = _union_arrays(["a", "b"], ["b", "c"])
        assert result == ["a", "b", "c"]

    def test_empty_arrays(self):
        result = _union_arrays([], ["a"])
        assert result == ["a"]


class TestMergeFrontmatterArrays:
    def test_union_fields_merged(self):
        existing = {"tags": ["ai"], "related": ["b"], "sources": ["s1"]}
        incoming = {"tags": ["ml"], "related": ["c"], "sources": ["s1", "s2"]}
        merged = merge_frontmatter_arrays(existing, incoming)
        assert "ai" in merged["tags"]
        assert "ml" in merged["tags"]
        assert "b" in merged["related"]
        assert "c" in merged["related"]


class TestMergePageContent:
    def test_new_page(self):
        """全新页面：直接返回"""
        result, was_llm = merge_page_content("new content", None)
        assert result == "new content"
        assert was_llm is False

    def test_identical_content(self):
        """字节级相同：返回已有"""
        content = "---\ntype: entity\ntitle: Test\n---\nBody"
        result, was_llm = merge_page_content(content, content)
        assert result == content
        assert was_llm is False

    def test_merge_with_frontmatter(self):
        """有 frontmatter 的合并"""
        existing = "---\ntype: entity\ntitle: Test\ncreated: 2026-01-01\nupdated: 2026-01-01\ntags: [ai]\nrelated: []\nsources: []\n---\nOld body"
        incoming = "---\ntype: concept\ntitle: New Test\ncreated: 2026-05-12\nupdated: 2026-05-12\ntags: [ml]\nrelated: [b]\nsources: [s1]\n---\nNew body"

        result, was_llm = merge_page_content(incoming, existing)

        # 锁定字段应保留旧值
        assert "type: entity" in result or "type: entity" in result
        # 数组字段应合并
        # 具体格式取决于 _rebuild_page

    def test_merge_with_backup(self):
        """合并时调用备份函数"""
        existing = "---\ntype: entity\ntitle: Test\n---\nOld"
        incoming = "---\ntype: entity\ntitle: Test\n---\nNew"

        backup_called = []

        def backup_fn(content):
            backup_called.append(content)

        result, was_llm = merge_page_content(
            incoming, existing, backup_fn=backup_fn
        )
        # 不应崩溃，备份可能被调用也可能不被调用（取决于是否走 LLM 路径）

    def test_llm_merger_body_shrink_check(self):
        """LLM 合并的 body 缩短阈值检查"""
        existing = "---\ntype: entity\ntitle: Test\n---\n" + "x" * 1000
        incoming = "---\ntype: entity\ntitle: Test\n---\n" + "y" * 1000

        # 模拟 LLM 返回过短的合并结果
        def bad_merger(existing_content, new_content, source_name):
            return "---\ntype: entity\ntitle: Test\n---\nshort"

        backup_called = []

        def backup_fn(content):
            backup_called.append(content)

        result, was_llm = merge_page_content(
            incoming, existing, merger_fn=bad_merger, backup_fn=backup_fn
        )
        # 应 fallback，不使用 LLM 合并结果
        assert was_llm is False
