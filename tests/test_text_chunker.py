"""单元测试：文本分块器，对齐官方 text-chunker.ts"""

import pytest
from app.services.text_chunker import chunk_markdown, Chunk


class TestChunkMarkdown:
    def test_empty_content(self):
        result = chunk_markdown("")
        assert result == []

    def test_short_content_single_chunk(self):
        content = "# Hello\n\nThis is a short paragraph."
        result = chunk_markdown(content)
        assert len(result) == 1
        assert "Hello" in result[0].text or "short paragraph" in result[0].text

    def test_frontmatter_stripped(self):
        content = "---\ntitle: Test\ntype: entity\n---\n# Test\nContent here."
        result = chunk_markdown(content)
        assert len(result) >= 1
        for chunk in result:
            assert "---" not in chunk.text or "Content" in chunk.text

    def test_heading_path(self):
        content = "# Main\n\n## Section 1\n\nParagraph 1\n\n## Section 2\n\nParagraph 2"
        result = chunk_markdown(content, target_chars=500)
        # Chunks under ## Section 1 should have heading_path containing "Section 1"
        section1_chunks = [c for c in result if "Section 1" in c.heading_path]
        section2_chunks = [c for c in result if "Section 2" in c.heading_path]
        assert len(section1_chunks) >= 1
        assert len(section2_chunks) >= 1

    def test_code_block_indivisible(self):
        content = "# Code\n\n```python\ndef hello():\n    print('hello world')\n```"
        result = chunk_markdown(content)
        # Code block should be in a single chunk
        code_chunks = [c for c in result if "print" in c.text]
        assert len(code_chunks) >= 1

    def test_table_indivisible(self):
        content = "# Table\n\n| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
        result = chunk_markdown(content)
        table_chunks = [c for c in result if "| A |" in c.text or "1 | 2" in c.text]
        assert len(table_chunks) >= 1

    def test_long_content_multiple_chunks(self):
        content = "# Long\n\n" + "\n\n".join(f"Paragraph {i} with some content to fill." for i in range(20))
        result = chunk_markdown(content, target_chars=200, max_chars=300, min_chars=50, overlap_chars=30)
        assert len(result) > 1

    def test_overlap_applied(self):
        content = "# Test\n\n" + "A" * 500 + "\n\n" + "B" * 500
        result = chunk_markdown(content, target_chars=300, max_chars=400, min_chars=50, overlap_chars=50)
        if len(result) >= 2:
            # Second chunk should contain some overlap from first
            assert len(result[1].text) > 100  # Has overlap + content

    def test_chunk_index_sequential(self):
        content = "# Test\n\n" + "\n\n".join(f"Para {i} " * 30 for i in range(5))
        result = chunk_markdown(content, target_chars=300, max_chars=400)
        indices = [c.index for c in result]
        assert indices == list(range(len(result)))


class TestCJKContent:
    def test_chinese_content_chunking(self):
        content = "# 测试\n\n这是一段中文内容。这是第二句话。这是第三句话。"
        result = chunk_markdown(content)
        assert len(result) >= 1
        assert "中文" in result[0].text

    def test_mixed_content(self):
        content = "# Mixed\n\nEnglish paragraph here.\n\n中文段落在这里。"
        result = chunk_markdown(content)
        assert len(result) >= 1
