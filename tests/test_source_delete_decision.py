"""测试 source_delete_decision — 对齐桌面版 decidePageFate()"""

import pytest
from app.services.source_delete_decision import decide_page_fate


class TestDecidePageFate:
    """三路决策：skip / keep / delete"""

    def test_skip_page_not_referencing_source(self):
        """页面不引用该 source → skip"""
        result = decide_page_fate(["X.md", "Y.md"], "Z.md")
        assert result["action"] == "skip"
        assert "Z.md" in result["reason"]

    def test_delete_only_source(self):
        """该 source 是页面唯一来源 → delete"""
        result = decide_page_fate(["A.md"], "A.md")
        assert result["action"] == "delete"
        assert result["updated_sources"] == []

    def test_keep_multiple_sources(self):
        """页面有多个来源，删除其中一个 → keep"""
        result = decide_page_fate(["A.md", "B.md", "C.md"], "B.md")
        assert result["action"] == "keep"
        assert result["updated_sources"] == ["A.md", "C.md"]

    def test_case_insensitive_match(self):
        """大小写不敏感匹配，对齐桌面版"""
        result = decide_page_fate(["Test.md"], "test.md")
        assert result["action"] == "delete"

    def test_keep_with_case_insensitive(self):
        """大小写不敏感匹配 keep 分支"""
        result = decide_page_fate(["A.md", "Test.md"], "test.md")
        assert result["action"] == "keep"
        assert result["updated_sources"] == ["A.md"]

    def test_skip_case_insensitive(self):
        """大小写不敏感匹配 skip 分支"""
        result = decide_page_fate(["x.md", "y.md"], "Z.md")
        assert result["action"] == "skip"

    def test_empty_sources(self):
        """空 sources 列表 → skip"""
        result = decide_page_fate([], "A.md")
        assert result["action"] == "skip"

    def test_delete_first_of_multiple(self):
        """删除多个来源中的第一个"""
        result = decide_page_fate(["A.md", "B.md"], "A.md")
        assert result["action"] == "keep"
        assert result["updated_sources"] == ["B.md"]

    def test_delete_last_of_multiple(self):
        """删除多个来源中的最后一个"""
        result = decide_page_fate(["A.md", "B.md"], "B.md")
        assert result["action"] == "keep"
        assert result["updated_sources"] == ["A.md"]
