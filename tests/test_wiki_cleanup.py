"""测试 wiki_cleanup — 对齐桌面版 wiki-cleanup.ts"""

import pytest
from app.services.wiki_cleanup import (
    normalize_wiki_ref_key,
    build_deleted_keys,
    DeletedPageInfo,
    extract_frontmatter_title,
    clean_index_listing,
    strip_deleted_wikilinks,
    write_frontmatter_array,
    parse_frontmatter_array,
)


class TestNormalizeWikiRefKey:
    """归一化 wiki 引用键"""

    def test_spaces_removed(self):
        assert normalize_wiki_ref_key("KV Cache") == "kvcache"

    def test_hyphens_removed(self):
        assert normalize_wiki_ref_key("kv-cache") == "kvcache"

    def test_underscores_removed(self):
        assert normalize_wiki_ref_key("kv_cache") == "kvcache"

    def test_path_prefix_removed(self):
        assert normalize_wiki_ref_key("wiki/concepts/kv-cache.md") == "kvcache"

    def test_case_insensitive(self):
        assert normalize_wiki_ref_key("KV-CACHE") == "kvcache"

    def test_backslash_normalized(self):
        assert normalize_wiki_ref_key("wiki\\concepts\\kv-cache.md") == "kvcache"

    def test_whitespace_trimmed(self):
        assert normalize_wiki_ref_key("  kv-cache  ") == "kvcache"

    def test_punctuation_preserved(self):
        """逗号等标点不去除，对齐桌面版"""
        assert "hello" in normalize_wiki_ref_key("Hello, World")
        assert normalize_wiki_ref_key("Hello, World") == "hello,world"


class TestBuildDeletedKeys:
    """构建归一化键集合"""

    def test_slug_and_title_both_included(self):
        infos = [DeletedPageInfo(slug="kv-cache", title="KV Cache")]
        keys = build_deleted_keys(infos)
        assert "kvcache" in keys

    def test_empty_title(self):
        infos = [DeletedPageInfo(slug="test-page", title="")]
        keys = build_deleted_keys(infos)
        assert "testpage" in keys

    def test_multiple_infos(self):
        infos = [
            DeletedPageInfo(slug="ai", title="AI"),
            DeletedPageInfo(slug="kv-cache", title="KV Cache"),
        ]
        keys = build_deleted_keys(infos)
        assert "ai" in keys
        assert "kvcache" in keys


class TestExtractFrontmatterTitle:
    """从 frontmatter 提取 title"""

    def test_plain_title(self):
        content = "---\ntitle: KV Cache\ntype: concept\n---\nBody"
        assert extract_frontmatter_title(content) == "KV Cache"

    def test_quoted_title(self):
        content = '---\ntitle: "KV Cache"\ntype: concept\n---\nBody'
        assert extract_frontmatter_title(content) == "KV Cache"

    def test_single_quoted_title(self):
        content = "---\ntitle: 'KV Cache'\ntype: concept\n---\nBody"
        assert extract_frontmatter_title(content) == "KV Cache"

    def test_no_title(self):
        content = "---\ntype: concept\n---\nBody"
        assert extract_frontmatter_title(content) == ""


class TestCleanIndexListing:
    """清理 index.md 条目"""

    def test_remove_deleted_entry(self):
        text = "- [[KV Cache]] Some description\n- [[AI]] Another"
        keys = {"kvcache"}
        result = clean_index_listing(text, keys)
        assert "[[KV Cache]]" not in result
        assert "[[AI]]" in result

    def test_no_false_positive(self):
        """删除 ai 不会误删 [[OpenAI]]，对齐桌面版 bug 修复"""
        text = "- [[OpenAI]] Desc\n- [[AI]] Desc\n- [[Constitutional AI]] Desc"
        keys = {"ai"}
        result = clean_index_listing(text, keys)
        assert "[[OpenAI]]" in result
        assert "[[AI]]" not in result
        assert "[[Constitutional AI]]" in result

    def test_asterisk_list(self):
        text = "* [[KV Cache]] Desc"
        keys = {"kvcache"}
        result = clean_index_listing(text, keys)
        assert "[[KV Cache]]" not in result

    def test_empty_keys(self):
        text = "- [[KV Cache]] Desc"
        result = clean_index_listing(text, set())
        assert "[[KV Cache]]" in result

    def test_alias_wikilink(self):
        """[[Target|Alias]] 格式"""
        text = "- [[KV Cache|KV]] Desc\n- [[AI]] Desc"
        keys = {"kvcache"}
        result = clean_index_listing(text, keys)
        assert "KV Cache" not in result
        assert "[[AI]]" in result


class TestStripDeletedWikilinks:
    """清理正文 wikilink"""

    def test_simple_wikilink_to_text(self):
        text = "See [[KV Cache]] for details."
        keys = {"kvcache"}
        result = strip_deleted_wikilinks(text, keys)
        assert result == "See KV Cache for details."

    def test_alias_wikilink_preserves_alias(self):
        text = "See [[KV Cache|caching]] for details."
        keys = {"kvcache"}
        result = strip_deleted_wikilinks(text, keys)
        assert result == "See caching for details."

    def test_kept_wikilink_unchanged(self):
        text = "See [[AI]] and [[KV Cache]] for details."
        keys = {"kvcache"}
        result = strip_deleted_wikilinks(text, keys)
        assert "[[AI]]" in result
        assert "[[KV Cache]]" not in result

    def test_no_false_positive(self):
        """删除 ai 不会误删 [[OpenAI]]"""
        text = "[[OpenAI]] and [[AI]]"
        keys = {"ai"}
        result = strip_deleted_wikilinks(text, keys)
        assert "[[OpenAI]]" in result
        assert "AI" in result
        assert "[[AI]]" not in result

    def test_empty_keys(self):
        text = "[[KV Cache]]"
        result = strip_deleted_wikilinks(text, set())
        assert result == "[[KV Cache]]"


class TestWriteFrontmatterArray:
    """重写 frontmatter 数组字段"""

    def test_replace_inline_array(self):
        content = "---\ntitle: Test\nsources: [A.md, B.md]\n---\nBody"
        result = write_frontmatter_array(content, "sources", ["A.md"])
        assert "A.md" in result
        assert "B.md" not in result
        assert "Body" in result

    def test_replace_multiline_array(self):
        content = "---\ntitle: Test\nsources:\n  - A.md\n  - B.md\n---\nBody"
        result = write_frontmatter_array(content, "sources", ["A.md"])
        assert "A.md" in result
        assert "Body" in result

    def test_add_new_field(self):
        content = "---\ntitle: Test\n---\nBody"
        result = write_frontmatter_array(content, "sources", ["A.md"])
        assert "sources" in result
        assert "A.md" in result

    def test_empty_array(self):
        content = "---\ntitle: Test\nsources:\n  - A.md\n---\nBody"
        result = write_frontmatter_array(content, "sources", [])
        assert "sources: []" in result

    def test_preserves_other_fields(self):
        content = "---\ntitle: Test\ntype: entity\nsources: [A.md]\n---\nBody"
        result = write_frontmatter_array(content, "sources", ["B.md"])
        assert "title: Test" in result
        assert "type: entity" in result


class TestParseFrontmatterArray:
    """解析 frontmatter 数组字段"""

    def test_inline_array(self):
        content = "---\nsources: [A.md, B.md]\n---\nBody"
        result = parse_frontmatter_array(content, "sources")
        assert "A.md" in result
        assert "B.md" in result

    def test_multiline_array(self):
        content = "---\nsources:\n  - A.md\n  - B.md\n---\nBody"
        result = parse_frontmatter_array(content, "sources")
        assert "A.md" in result
        assert "B.md" in result

    def test_missing_field(self):
        content = "---\ntitle: Test\n---\nBody"
        result = parse_frontmatter_array(content, "sources")
        assert result == []

    def test_no_frontmatter(self):
        content = "Just body text"
        result = parse_frontmatter_array(content, "sources")
        assert result == []
