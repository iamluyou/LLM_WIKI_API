"""单元测试：Review 块解析 + Frontmatter 校验 + 语言守卫"""

import pytest
from app.parsers.review_blocks import parse_review_blocks
from app.parsers.frontmatter import validate_frontmatter, set_frontmatter_field, extract_frontmatter_raw
from app.safety.language_guard import detect_script_family, content_matches_target_language


class TestParseReviewBlocks:
    def test_basic_review(self):
        raw = (
            "---REVIEW: contradiction | 定义冲突---\n"
            "Two pages define this differently\n"
            "OPTIONS: Create Page | Skip\n"
            "PAGES: wiki/entities/a.md, wiki/concepts/b.md\n"
            "---END REVIEW---"
        )
        reviews = parse_review_blocks(raw)
        assert len(reviews) == 1
        assert reviews[0].type == "contradiction"
        assert reviews[0].title == "定义冲突"
        assert "Create Page" in reviews[0].options
        assert len(reviews[0].pages) == 2

    def test_multiple_reviews(self):
        raw = (
            "---REVIEW: duplicate | 重复页面---\nDesc1\n---END REVIEW---\n"
            "---REVIEW: missing-page | 缺失页面---\nDesc2\n---END REVIEW---"
        )
        reviews = parse_review_blocks(raw)
        assert len(reviews) == 2

    def test_invalid_type_downgraded(self):
        raw = "---REVIEW: invalid-type | Test---\nDesc\n---END REVIEW---"
        reviews = parse_review_blocks(raw)
        assert reviews[0].type == "confirm"  # 降级

    def test_search_field(self):
        raw = "---REVIEW: suggestion | 新概念---\nSEARCH: query1 | query2 | query3\n---END REVIEW---"
        reviews = parse_review_blocks(raw)
        assert len(reviews[0].search) == 3


class TestValidateFrontmatter:
    def test_valid_entity(self):
        fm = {
            "type": "entity",
            "title": "Test",
            "created": "2026-05-12",
            "updated": "2026-05-12",
            "tags": [],
            "related": [],
            "sources": [],
        }
        validated, errors = validate_frontmatter(fm)
        assert len(errors) == 0
        assert validated is not None
        assert validated.title == "Test"

    def test_missing_required_field(self):
        fm = {"type": "entity"}  # 缺少 title, created, updated
        validated, errors = validate_frontmatter(fm)
        assert len(errors) > 0

    def test_invalid_page_type(self):
        fm = {
            "type": "invalid",
            "title": "Test",
            "created": "2026-05-12",
            "updated": "2026-05-12",
        }
        validated, errors = validate_frontmatter(fm)
        assert len(errors) > 0

    def test_source_frontmatter(self):
        fm = {
            "type": "source",
            "title": "Test Source",
            "created": "2026-05-12",
            "updated": "2026-05-12",
            "tags": [],
            "related": [],
            "sources": [],
            "authors": ["Author A"],
            "year": 2026,
        }
        validated, errors = validate_frontmatter(fm)
        assert len(errors) == 0


class TestSetFrontmatterField:
    def test_update_existing_field(self):
        content = "---\ntitle: Old\n---\nBody"
        result = set_frontmatter_field(content, "title", "New")
        assert "title: New" in result

    def test_add_new_field(self):
        content = "---\ntitle: Test\n---\nBody"
        result = set_frontmatter_field(content, "updated", "2026-05-12")
        assert "updated: 2026-05-12" in result


class TestLanguageGuard:
    def test_detect_cjk(self):
        assert detect_script_family("这是一段中文文本") == "cjk"

    def test_detect_latin(self):
        assert detect_script_family("This is English text") == "latin"

    def test_content_matches_chinese(self):
        content = "---\ntype: concept\n---\n这是一个概念页面"
        assert content_matches_target_language(content, "chinese") is True

    def test_content_mismatch(self):
        content = "---\ntype: concept\n---\nThis is English content"
        assert content_matches_target_language(content, "chinese") is False

    def test_empty_content_passes(self):
        assert content_matches_target_language("", "chinese") is True
