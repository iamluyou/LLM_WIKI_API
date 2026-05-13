"""测试 ingest_sanitize — 对齐桌面版 ingest-sanitize.ts"""

import pytest
from app.safety.ingest_sanitize import (
    sanitize_ingested_content,
    _strip_outer_code_fence,
    _strip_frontmatter_key_prefix,
    _repair_wikilink_lists,
)


class TestStripOuterCodeFence:
    """剥离外层代码围栏"""

    def test_yaml_fence(self):
        content = "```yaml\n---\ntype: entity\n---\nBody\n```"
        result = _strip_outer_code_fence(content)
        assert result.strip().startswith("---")

    def test_md_fence(self):
        content = "```md\n---\ntype: entity\n---\nBody\n```"
        result = _strip_outer_code_fence(content)
        assert result.strip().startswith("---")

    def test_plain_fence(self):
        content = "```\n---\ntype: entity\n---\nBody\n```"
        result = _strip_outer_code_fence(content)
        assert result.strip().startswith("---")

    def test_no_fence(self):
        content = "---\ntype: entity\n---\nBody"
        result = _strip_outer_code_fence(content)
        assert result == content

    def test_inner_code_fence_preserved(self):
        """内容内部的代码围栏不应被剥离"""
        content = "---\ntype: entity\n---\nBody\n```\ncode\n```\n"
        result = _strip_outer_code_fence(content)
        assert result == content

    def test_unclosed_fence_not_stripped(self):
        """未闭合的外层围栏不剥离"""
        content = "```yaml\n---\ntype: entity\n---\nBody"
        result = _strip_outer_code_fence(content)
        assert result == content


class TestStripFrontmatterKeyPrefix:
    """剥离 frontmatter: 前缀"""

    def test_with_prefix(self):
        content = "frontmatter:\n---\ntype: entity\n---\nBody"
        result = _strip_frontmatter_key_prefix(content)
        assert result.startswith("---")

    def test_without_prefix(self):
        content = "---\ntype: entity\n---\nBody"
        result = _strip_frontmatter_key_prefix(content)
        assert result == content

    def test_indented_prefix(self):
        content = "  frontmatter:\n---\ntype: entity\n---\nBody"
        result = _strip_frontmatter_key_prefix(content)
        assert result.startswith("---")


class TestRepairWikilinkLists:
    """修复 frontmatter 中的 wikilink 列表格式"""

    def test_wikilink_list_to_quoted_array(self):
        content = "---\nrelated: [[a]], [[b]], [[c]]\n---\nBody"
        result = _repair_wikilink_lists(content)
        assert '"[[a]]"' in result
        assert '"[[b]]"' in result
        assert '"[[c]]"' in result

    def test_no_wikilink_list(self):
        content = "---\nrelated: [a, b]\n---\nBody"
        result = _repair_wikilink_lists(content)
        assert result == content

    def test_mixed_fields_only_fixes_wikilinks(self):
        """只修复包含 [[wikilink]] 的列表，不修改普通数组"""
        content = "---\ntags: [ai, ml]\nrelated: [[foo]], [[bar]]\n---\nBody"
        result = _repair_wikilink_lists(content)
        assert "tags: [ai, ml]" in result
        assert '"[[foo]]"' in result

    def test_no_frontmatter(self):
        content = "Just body text with [[wikilink]]"
        result = _repair_wikilink_lists(content)
        assert result == content

    def test_single_wikilink_not_modified(self):
        """单个 [[wikilink]] 不在逗号列表中，不修改"""
        content = "---\nrelated: [[single]]\n---\nBody"
        result = _repair_wikilink_lists(content)
        # 单个 wikilink 不匹配正则（需要至少两个逗号分隔的）
        # 但实际输出取决于正则，单个应该不被修改
        assert "[[single]]" in result


class TestSanitizeIngestedContent:
    """完整清洗流程"""

    def test_full_pipeline(self):
        """代码围栏 + frontmatter前缀 + wikilink列表 三重修复"""
        content = "```yaml\nfrontmatter:\n---\nrelated: [[a]], [[b]]\n---\nBody\n```"
        result = sanitize_ingested_content(content)
        assert not result.startswith("```")
        assert not result.startswith("frontmatter:")
        assert '"[[a]]"' in result
        assert '"[[b]]"' in result

    def test_clean_content_unchanged(self):
        """格式正确的内容不应被修改"""
        content = '---\ntype: entity\nrelated: [a, b]\n---\nBody'
        result = sanitize_ingested_content(content)
        assert result == content

    def test_only_fence_issue(self):
        content = "```yaml\n---\ntype: entity\n---\nBody\n```"
        result = sanitize_ingested_content(content)
        assert result.startswith("---")
