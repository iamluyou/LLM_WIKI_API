"""单元测试：parseFileBlocks（6类解析危害 H1-H6）"""

import pytest
from app.parsers.file_blocks import parse_file_blocks


class TestParseFileBlocks:
    """对齐桌面版 parseFileBlocks 测试"""

    def test_basic_single_block(self):
        raw = "---FILE: wiki/entities/test.md---\n# Test\nContent\n---END FILE---"
        result = parse_file_blocks(raw)
        assert len(result.blocks) == 1
        assert result.blocks[0].path == "wiki/entities/test.md"
        assert "# Test" in result.blocks[0].content
        assert "Content" in result.blocks[0].content
        assert len(result.warnings) == 0

    def test_multiple_blocks(self):
        raw = (
            "---FILE: wiki/entities/a.md---\nContent A\n---END FILE---\n\n"
            "---FILE: wiki/concepts/b.md---\nContent B\n---END FILE---"
        )
        result = parse_file_blocks(raw)
        assert len(result.blocks) == 2
        assert result.blocks[0].path == "wiki/entities/a.md"
        assert result.blocks[1].path == "wiki/concepts/b.md"

    # H1: CRLF 行尾
    def test_h1_crlf(self):
        raw = "---FILE: wiki/test.md---\r\nContent\r\n---END FILE---"
        result = parse_file_blocks(raw)
        assert len(result.blocks) == 1
        assert "Content" in result.blocks[0].content

    # H2: 流截断
    def test_h2_truncated_block(self):
        raw = "---FILE: wiki/test.md---\nContent without closer"
        result = parse_file_blocks(raw)
        assert len(result.blocks) == 1
        assert len(result.warnings) >= 1
        assert "missing" in result.warnings[0].lower() or "truncated" in result.warnings[0].lower()

    # H3: 大小写不敏感 + 宽容空白
    def test_h3_case_insensitive(self):
        raw = "---file: wiki/test.md---\nContent\n---end file---"
        result = parse_file_blocks(raw)
        assert len(result.blocks) == 1

    def test_h3_extra_spaces(self):
        raw = "---  FILE :  wiki/test.md  ---\nContent\n---  END  FILE  ---"
        result = parse_file_blocks(raw)
        assert len(result.blocks) == 1

    # H4: 代码围栏内的 END FILE
    def test_h4_fence_inside_code_block(self):
        raw = (
            "---FILE: wiki/test.md---\n"
            "```\n---END FILE---\n```\n"
            "Real content\n"
            "---END FILE---"
        )
        result = parse_file_blocks(raw)
        assert len(result.blocks) == 1
        assert "Real content" in result.blocks[0].content

    # H5: 空路径
    def test_h5_empty_path(self):
        raw = "---FILE: ---\nContent\n---END FILE---"
        result = parse_file_blocks(raw)
        assert len(result.blocks) == 0
        assert len(result.warnings) >= 1

    def test_h5_whitespace_path(self):
        raw = "---FILE:    ---\nContent\n---END FILE---"
        result = parse_file_blocks(raw)
        assert len(result.blocks) == 0

    # 额外：混合内容（preamble 被忽略）
    def test_ignores_preamble(self):
        raw = "Here are the files:\n\n---FILE: wiki/test.md---\nContent\n---END FILE---"
        result = parse_file_blocks(raw)
        assert len(result.blocks) == 1

    # 额外：frontmatter 在块内
    def test_block_with_frontmatter(self):
        raw = (
            "---FILE: wiki/entities/test.md---\n"
            "---\ntype: entity\ntitle: Test\n---\n# Test\nContent\n"
            "---END FILE---"
        )
        result = parse_file_blocks(raw)
        assert len(result.blocks) == 1
        assert "type: entity" in result.blocks[0].content
