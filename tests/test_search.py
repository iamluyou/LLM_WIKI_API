"""单元测试：混合检索 + CJK 分词 + RRF"""

import pytest
from app.services.search import tokenize_query, score_file, build_snippet


class TestTokenizeQuery:
    """对齐桌面版 tokenizeQuery"""

    def test_english_query(self):
        tokens = tokenize_query("what is RAG")
        assert "rag" in [t.lower() for t in tokens]
        # 停用词应被过滤
        assert "what" not in [t.lower() for t in tokens]
        assert "is" not in [t.lower() for t in tokens]

    def test_chinese_query(self):
        tokens = tokenize_query("默会知识")
        # 应生成 bigram
        assert "默会" in tokens
        assert "知识" in tokens
        # 原始 token
        assert "默会知识" in tokens

    def test_chinese_with_stopwords(self):
        tokens = tokenize_query("什么是知识管理")
        # 停用词 "什么" 应被过滤
        lower_tokens = [t.lower() for t in tokens]
        assert "什么" not in lower_tokens

    def test_mixed_query(self):
        tokens = tokenize_query("RAG 在 AI 中的应用")
        lower_tokens = [t.lower() for t in tokens]
        assert "rag" in lower_tokens
        assert "ai" in lower_tokens

    def test_short_query(self):
        tokens = tokenize_query("AI")
        assert "ai" in [t.lower() for t in tokens]

    def test_empty_query(self):
        tokens = tokenize_query("")
        assert tokens == []


class TestScoreFile:
    def test_filename_exact_match(self):
        content = "# Test\nSome content"
        score = score_file(content, "attention.md", ["attention"], "attention")
        assert score is not None
        assert score >= 200  # FILENAME_EXACT_BONUS

    def test_phrase_in_title(self):
        content = "# Knowledge Management\nSome content"
        score = score_file(content, "test.md", ["knowledge"], "knowledge")
        assert score is not None
        assert score >= 50  # PHRASE_IN_TITLE_BONUS

    def test_no_match(self):
        content = "# Something\nSome content"
        score = score_file(content, "test.md", ["quantum"], "quantum")
        assert score is None


class TestBuildSnippet:
    def test_query_found(self):
        content = "This is a long text about machine learning and AI applications in research."
        snippet = build_snippet(content, "machine learning")
        assert "machine learning" in snippet.lower()

    def test_query_not_found(self):
        content = "Short text"
        snippet = build_snippet(content, "quantum")
        assert len(snippet) > 0

    def test_short_content(self):
        content = "AI"
        snippet = build_snippet(content, "AI")
        assert "AI" in snippet
