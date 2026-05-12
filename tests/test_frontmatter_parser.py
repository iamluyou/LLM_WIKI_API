"""测试 frontmatter 解析器，对齐桌面版 frontmatter.ts"""

import pytest
from app.parsers.frontmatter import (
    parse_frontmatter,
    validate_frontmatter,
    extract_frontmatter_raw,
    set_frontmatter_field,
)


class TestParseFrontmatter:
    def test_basic_parse(self):
        content = "---\ntitle: Test\ntype: entity\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nBody"
        meta, body = parse_frontmatter(content)
        assert meta["title"] == "Test"
        assert meta["type"] == "entity"
        assert "Body" in body

    def test_no_frontmatter(self):
        content = "Just plain text"
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert "plain text" in body

    def test_frontmatter_with_lists(self):
        content = "---\ntitle: Test\ntags:\n  - ai\n  - ml\n---\nBody"
        meta, body = parse_frontmatter(content)
        assert "tags" in meta


class TestValidateFrontmatter:
    def test_valid_entity(self):
        meta = {
            "type": "entity",
            "title": "AI",
            "created": "2026-01-01",
            "updated": "2026-01-01",
            "sources": ["test.md"],
        }
        validated, errors = validate_frontmatter(meta)
        assert validated is not None
        assert errors == []

    def test_missing_required_field(self):
        meta = {"type": "entity", "title": "AI"}
        validated, errors = validate_frontmatter(meta)
        assert validated is None
        assert any("created" in e for e in errors)

    def test_invalid_page_type(self):
        meta = {
            "type": "invalid_type",
            "title": "Test",
            "created": "2026-01-01",
            "updated": "2026-01-01",
        }
        validated, errors = validate_frontmatter(meta)
        assert validated is None
        assert any("Invalid page type" in e for e in errors)

    def test_source_frontmatter(self):
        meta = {
            "type": "source",
            "title": "Source Doc",
            "created": "2026-01-01",
            "updated": "2026-01-01",
            "authors": ["Author A"],
            "url": "https://example.com",
        }
        validated, errors = validate_frontmatter(meta)
        assert validated is not None
        assert validated.authors == ["Author A"]

    def test_invalid_date_format(self):
        meta = {
            "type": "entity",
            "title": "AI",
            "created": "not-a-date",
            "updated": "2026-01-01",
        }
        validated, errors = validate_frontmatter(meta)
        assert validated is None
        assert any("date" in e.lower() for e in errors)


class TestExtractFrontmatterRaw:
    def test_basic_extraction(self):
        content = "---\ntitle: Test\n---\nBody"
        result = extract_frontmatter_raw(content)
        assert "title: Test" in result

    def test_no_frontmatter(self):
        content = "Just body"
        result = extract_frontmatter_raw(content)
        assert result is None


class TestSetFrontmatterField:
    def test_replace_existing(self):
        content = "---\ntitle: Old\ntype: entity\n---\nBody"
        result = set_frontmatter_field(content, "title", "New")
        assert "title: New" in result
        assert "title: Old" not in result
        assert "Body" in result

    def test_add_new_field(self):
        content = "---\ntitle: Test\n---\nBody"
        result = set_frontmatter_field(content, "type", "concept")
        assert "type: concept" in result

    def test_no_frontmatter_returns_unchanged(self):
        content = "Just text"
        result = set_frontmatter_field(content, "title", "Test")
        assert result == content

    def test_preserves_other_fields(self):
        content = "---\ntitle: Test\ntype: entity\n---\nBody"
        result = set_frontmatter_field(content, "title", "New")
        assert "type: entity" in result
