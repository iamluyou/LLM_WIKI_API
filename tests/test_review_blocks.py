"""测试 review_blocks 解析器"""

import pytest
from app.parsers.review_blocks import parse_review_blocks, ParsedReviewBlock


class TestParseReviewBlocks:
    def test_basic_review_block(self):
        raw = (
            "---REVIEW: contradiction | Conflicting claims ---\n"
            "Entity A says X, Entity B says Y\n"
            "---END REVIEW---"
        )
        results = parse_review_blocks(raw)
        assert len(results) == 1
        assert results[0].type == "contradiction"
        assert "Conflicting claims" in results[0].title

    def test_review_with_options(self):
        raw = (
            "---REVIEW: suggestion | Improve section ---\n"
            "Some description\n"
            "OPTIONS: merge|split|keep\n"
            "---END REVIEW---"
        )
        results = parse_review_blocks(raw)
        assert len(results) == 1
        assert results[0].options == ["merge", "split", "keep"]

    def test_review_with_pages(self):
        raw = (
            "---REVIEW: duplicate | Same content ---\n"
            "PAGES: entity-a.md, entity-b.md\n"
            "---END REVIEW---"
        )
        results = parse_review_blocks(raw)
        assert results[0].pages == ["entity-a.md", "entity-b.md"]

    def test_review_with_search(self):
        raw = (
            "---REVIEW: missing-page | Need page ---\n"
            "SEARCH: topic-a|topic-b\n"
            "---END REVIEW---"
        )
        results = parse_review_blocks(raw)
        assert results[0].search == ["topic-a", "topic-b"]

    def test_invalid_type_degrades_to_confirm(self):
        raw = (
            "---REVIEW: invalid-type | Test ---\n"
            "Description\n"
            "---END REVIEW---"
        )
        results = parse_review_blocks(raw)
        assert results[0].type == "confirm"

    def test_multiple_review_blocks(self):
        raw = (
            "---REVIEW: contradiction | C1 ---\nD1\n---END REVIEW---\n"
            "---REVIEW: suggestion | S1 ---\nD2\n---END REVIEW---"
        )
        results = parse_review_blocks(raw)
        assert len(results) == 2
        assert results[0].type == "contradiction"
        assert results[1].type == "suggestion"

    def test_no_review_blocks(self):
        raw = "Just some regular text without review blocks"
        results = parse_review_blocks(raw)
        assert results == []

    def test_description_excludes_metadata_lines(self):
        raw = (
            "---REVIEW: suggestion | Test ---\n"
            "Real description here\n"
            "OPTIONS: a|b\n"
            "---END REVIEW---"
        )
        results = parse_review_blocks(raw)
        assert "Real description" in results[0].description
        assert "OPTIONS" not in results[0].description

    def test_all_valid_types(self):
        for rtype in ["contradiction", "duplicate", "missing-page", "suggestion", "confirm"]:
            raw = f"---REVIEW: {rtype} | Title ---\nDesc\n---END REVIEW---"
            results = parse_review_blocks(raw)
            assert results[0].type == rtype
