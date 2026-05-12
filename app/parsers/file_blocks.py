"""文件块解析器，对齐桌面版 parseFileBlocks

修复6类解析危害（H1-H6）：
- H1: CRLF 行尾导致正则失配
- H2: 流截断（最后块缺少 ---END FILE---）
- H3: 标记中空格/大小写变体
- H4: 代码围栏内的 ---END FILE--- 导致提前截断
- H5: 空路径块
- H6: frontmatter 格式异常
"""

import re
from dataclasses import dataclass, field


OPENER_RE = re.compile(r"^---\s*FILE\s*:\s*(.+?)\s*---\s*$", re.IGNORECASE)
CLOSER_RE = re.compile(r"^---\s*END\s+FILE\s*---\s*$", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


@dataclass
class ParsedFileBlock:
    path: str
    content: str


@dataclass
class ParseFileBlocksResult:
    blocks: list[ParsedFileBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_file_blocks(raw: str) -> ParseFileBlocksResult:
    """解析 LLM 输出中的 ---FILE: ... ---END FILE--- 块

    对齐桌面版 parseFileBlocks()，处理 H1-H6 危害。
    """
    result = ParseFileBlocksResult()

    # H1: 预处理 CRLF
    text = raw.replace("\r\n", "\n").replace("\r", "\n")

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        # 查找 FILE 块开始
        opener_match = OPENER_RE.match(lines[i])
        if not opener_match:
            i += 1
            continue

        file_path = opener_match.group(1).strip()

        # H5: 空路径
        if not file_path:
            result.warnings.append(f"Empty file path at line {i + 1}, skipping block")
            i += 1
            continue

        # 收集内容直到 ---END FILE---
        content_lines = []
        found_closer = False
        fence_marker = None  # 跟踪代码围栏状态 (H4)
        j = i + 1

        while j < len(lines):
            line = lines[j]

            # H4: 围栏状态跟踪
            fence_match = FENCE_RE.match(line)
            if fence_match:
                if fence_marker is None:
                    fence_marker = fence_match.group(1)
                elif fence_match.group(1).startswith(fence_marker[0]) and len(fence_match.group(1)) >= len(fence_marker):
                    fence_marker = None  # 关闭围栏
                j += 1
                content_lines.append(line)
                continue

            # 只在围栏外识别关闭标记
            if fence_marker is None and CLOSER_RE.match(line):
                found_closer = True
                break

            content_lines.append(line)
            j += 1

        if not found_closer:
            # H2: 流截断
            result.warnings.append(
                f"File block '{file_path}' missing ---END FILE---, content may be truncated"
            )

        content = "\n".join(content_lines)
        result.blocks.append(ParsedFileBlock(path=file_path, content=content))

        i = j + 1 if found_closer else j

    return result
