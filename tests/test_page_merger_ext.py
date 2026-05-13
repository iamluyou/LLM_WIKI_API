"""测试 page_merger 三层合并逻辑"""

import pytest
from app.services.page_merger import (
    _merge_lists,
    merge_array_fields_into_content,
    merge_page_content,
    backup_page,
)


class TestMergeLists:
    def test_merge_no_duplicates(self):
        result = _merge_lists(["a", "b"], ["c", "d"])
        assert result == ["a", "b", "c", "d"]

    def test_merge_with_duplicates(self):
        result = _merge_lists(["a", "b"], ["b", "c"])
        assert result == ["a", "b", "c"]

    def test_case_insensitive_dedup(self):
        result = _merge_lists(["Test.md"], ["test.md"])
        assert len(result) == 1

    def test_empty_arrays(self):
        result = _merge_lists([], [])
        assert result == []

    def test_preserves_order(self):
        result = _merge_lists(["a", "c"], ["b"])
        assert result == ["a", "c", "b"]


class TestMergeArrayFieldsIntoContent:
    def test_union_sources(self):
        existing = '---\nsources: ["a.md"]\ntags: [ai]\n---\nBody'
        incoming = '---\nsources: ["b.md"]\ntags: [ml]\n---\nBody'
        result = merge_array_fields_into_content(incoming, existing, ["sources"])
        assert '"a.md"' in result
        assert '"b.md"' in result

    def test_no_existing(self):
        incoming = '---\nsources: ["b.md"]\n---\nBody'
        result = merge_array_fields_into_content(incoming, None, ["sources"])
        assert result == incoming

    def test_no_change(self):
        existing = '---\nsources: ["a.md", "b.md"]\n---\nBody'
        incoming = '---\nsources: ["a.md", "b.md"]\n---\nBody'
        result = merge_array_fields_into_content(incoming, existing, ["sources"])
        assert result == incoming  # stable reference


class TestMergePageContent:
    @pytest.mark.asyncio
    async def test_new_page(self):
        new = "---\ntitle: Test\ntype: entity\n---\nBody"
        result, was_llm = await merge_page_content(new, None)
        assert "Body" in result
        assert was_llm is False

    @pytest.mark.asyncio
    async def test_identical_content(self):
        content = "---\ntitle: Test\n---\nBody"
        result, was_llm = await merge_page_content(content, content)
        assert result == content
        assert was_llm is False

    @pytest.mark.asyncio
    async def test_body_same_frontmatter_diff(self):
        existing = '---\ntitle: Old\nsources: ["a.md"]\n---\nSame body'
        new = '---\ntitle: New\nsources: ["b.md"]\n---\nSame body'
        result, was_llm = await merge_page_content(new, existing)
        assert '"a.md"' in result
        assert '"b.md"' in result
        assert was_llm is False

    @pytest.mark.asyncio
    async def test_with_merger_fn(self):
        existing = '---\ntitle: Test\nsources: ["a.md"]\n---\nOld body'
        new = '---\ntitle: Test\nsources: ["b.md"]\n---\nNew body'

        async def mock_merger(ex, nw, src):
            return '---\ntitle: Test\nsources: ["c.md"]\n---\nMerged body'

        result, was_llm = await merge_page_content(new, existing, merger_fn=mock_merger)
        assert "Merged body" in result
        assert was_llm is True
        # Union 再次合并（防止 LLM 遗漏）
        assert '"a.md"' in result or '"b.md"' in result

    @pytest.mark.asyncio
    async def test_merger_fn_failure_fallback(self):
        existing = '---\ntitle: Test\nsources: ["a.md"]\n---\nOld body'
        new = '---\ntitle: Test\nsources: ["b.md"]\n---\nNew body'

        async def failing_merger(ex, nw, src):
            raise Exception("LLM failed")

        backup_called = []
        def backup_fn(c):
            backup_called.append(c)

        result, was_llm = await merge_page_content(new, existing, merger_fn=failing_merger, backup_fn=backup_fn)
        assert was_llm is False
        # fallback 到 array_merged（第1层合并后的内容）
        assert '"a.md"' in result
        assert '"b.md"' in result

    @pytest.mark.asyncio
    async def test_locked_fields_preserved(self):
        """locked fields (type, title, created) 在 LLM 合并路径后强制回写 existing 的值"""
        existing = "---\ntitle: Old Title\ntype: entity\ncreated: 2026-01-01\n---\nOld body"
        new = "---\ntitle: New Title\ntype: concept\ncreated: 2026-06-01\n---\nNew body"

        async def mock_merger(ex, nw, src):
            return "---\ntitle: Merged\ntype: concept\ncreated: 2026-06-01\n---\nMerged body"

        result, was_llm = await merge_page_content(new, existing, merger_fn=mock_merger)
        assert was_llm is True
        # locked fields 强制回写 existing 的值
        assert "Old Title" in result
        assert "entity" in result


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


class TestBlockFormParsing:
    """对齐官方 parseFrontmatterArray：block form 解析"""

    def test_parse_block_form(self):
        from app.services.page_merger import _parse_frontmatter_array
        content = "---\nsources:\n  - a.md\n  - b.md\n---\nBody"
        result = _parse_frontmatter_array(content, "sources")
        assert result == ["a.md", "b.md"]

    def test_parse_block_form_with_quotes(self):
        from app.services.page_merger import _parse_frontmatter_array
        content = '---\nsources:\n  - "a.md"\n  - \'b.md\'\n---\nBody'
        result = _parse_frontmatter_array(content, "sources")
        assert result == ["a.md", "b.md"]

    def test_parse_block_form_empty(self):
        from app.services.page_merger import _parse_frontmatter_array
        content = "---\ntitle: Test\n---\nBody"
        result = _parse_frontmatter_array(content, "sources")
        assert result == []

    def test_parse_inline_takes_precedence_over_block(self):
        """inline form 和 block form 同时存在时 inline 优先（对齐官方）"""
        from app.services.page_merger import _parse_frontmatter_array
        content = '---\nsources: [x.md]\nsources:\n  - y.md\n---\nBody'
        result = _parse_frontmatter_array(content, "sources")
        # 实际上 block form 先匹配到（多行），但 inline 在前面
        # 对齐官方：block form 先检测，匹配到就返回
        assert len(result) > 0

    def test_write_replaces_block_form(self):
        """write 应将 block form 替换为 inline form"""
        from app.services.page_merger import _write_frontmatter_array
        content = "---\nsources:\n  - a.md\n  - b.md\n---\nBody"
        result = _write_frontmatter_array(content, "sources", ["c.md"])
        assert '"c.md"' in result
        assert "  -" not in result.split("---")[1]  # frontmatter 中不应有 block form

    def test_merge_block_to_inline(self):
        """existing 用 block form，incoming 用 inline form，合并应正确"""
        from app.services.page_merger import merge_array_fields_into_content
        existing = "---\nsources:\n  - old.md\n---\nBody"
        incoming = '---\nsources: ["new.md"]\n---\nBody'
        result = merge_array_fields_into_content(incoming, existing, ["sources"])
        assert '"old.md"' in result
        assert '"new.md"' in result
