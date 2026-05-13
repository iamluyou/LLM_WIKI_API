"""单元测试：页面三层合并 + 健全性检查"""

import pytest
from app.services.page_merger import (
    merge_page_content,
    merge_array_fields_into_content,
    _merge_lists,
    _parse_frontmatter_array,
    _write_frontmatter_array,
)


class TestMergeLists:
    def test_merge_no_duplicates(self):
        result = _merge_lists(["a", "b"], ["c", "d"])
        assert result == ["a", "b", "c", "d"]

    def test_merge_with_duplicates(self):
        result = _merge_lists(["a", "b"], ["b", "c"])
        assert result == ["a", "b", "c"]

    def test_empty_arrays(self):
        result = _merge_lists([], ["a"])
        assert result == ["a"]


class TestParseFrontmatterArray:
    def test_inline_form(self):
        content = '---\nsources: ["a", "b"]\n---\nBody'
        result = _parse_frontmatter_array(content, "sources")
        assert result == ["a", "b"]

    def test_bare_inline_form(self):
        content = "---\nsources: [a, b]\n---\nBody"
        result = _parse_frontmatter_array(content, "sources")
        assert result == ["a", "b"]

    def test_missing_field(self):
        content = "---\ntitle: Test\n---\nBody"
        result = _parse_frontmatter_array(content, "sources")
        assert result == []


class TestWriteFrontmatterArray:
    def test_replace_existing(self):
        content = '---\nsources: ["old"]\n---\nBody'
        result = _write_frontmatter_array(content, "sources", ["a", "b"])
        assert '"a"' in result
        assert '"b"' in result

    def test_add_new_field(self):
        content = "---\ntitle: Test\n---\nBody"
        result = _write_frontmatter_array(content, "sources", ["a"])
        assert '"a"' in result


class TestMergeArrayFieldsIntoContent:
    def test_union_sources(self):
        existing = '---\nsources: ["s1"]\ntags: [ai]\n---\nBody'
        incoming = '---\nsources: ["s2"]\ntags: [ml]\n---\nBody'
        result = merge_array_fields_into_content(incoming, existing, ["sources"])
        assert '"s1"' in result
        assert '"s2"' in result


class TestMergePageContent:
    @pytest.mark.asyncio
    async def test_new_page(self):
        """全新页面：直接返回"""
        result, was_llm = await merge_page_content("new content", None)
        assert result == "new content"
        assert was_llm is False

    @pytest.mark.asyncio
    async def test_identical_content(self):
        """字节级相同：返回已有"""
        content = "---\ntype: entity\ntitle: Test\n---\nBody"
        result, was_llm = await merge_page_content(content, content)
        assert result == content
        assert was_llm is False

    @pytest.mark.asyncio
    async def test_merge_with_frontmatter(self):
        """有 frontmatter 的合并：body 不同走 merger 或 fallback"""
        existing = "---\ntype: entity\ntitle: Test\ncreated: 2026-01-01\nupdated: 2026-01-01\ntags: [ai]\nrelated: []\nsources: []\n---\nOld body"
        incoming = "---\ntype: concept\ntitle: New Test\ncreated: 2026-05-12\nupdated: 2026-05-12\ntags: [ml]\nrelated: [b]\nsources: [s1]\n---\nNew body"

        result, was_llm = await merge_page_content(incoming, existing)

        # 锁定字段应保留旧值
        assert "type: entity" in result
        assert "title: Test" in result

    @pytest.mark.asyncio
    async def test_merge_with_backup(self):
        """合并时调用备份函数"""
        existing = "---\ntype: entity\ntitle: Test\n---\nOld"
        incoming = "---\ntype: entity\ntitle: Test\n---\nNew"

        backup_called = []

        def backup_fn(content):
            backup_called.append(content)

        result, was_llm = await merge_page_content(
            incoming, existing, backup_fn=backup_fn
        )

    @pytest.mark.asyncio
    async def test_llm_merger_body_shrink_check(self):
        """LLM 合并的 body 缩短阈值检查"""
        existing = "---\ntype: entity\ntitle: Test\n---\n" + "x" * 1000
        incoming = "---\ntype: entity\ntitle: Test\n---\n" + "y" * 1000

        # 模拟 LLM 返回过短的合并结果
        async def bad_merger(existing_content, new_content, source_name):
            return "---\ntype: entity\ntitle: Test\n---\nshort"

        backup_called = []

        def backup_fn(content):
            backup_called.append(content)

        result, was_llm = await merge_page_content(
            incoming, existing, merger_fn=bad_merger, backup_fn=backup_fn
        )
        # 应 fallback，不使用 LLM 合并结果
        assert was_llm is False
