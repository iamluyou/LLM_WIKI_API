"""Review 块解析器，对齐桌面版 parseReviewBlocks"""

import re
from dataclasses import dataclass, field


REVIEW_BLOCK_RE = re.compile(
    r"---REVIEW:\s*(\w[\w-]*)\s*\|\s*(.+?)\s*---\n([\s\S]*?)---END REVIEW---",
    re.MULTILINE,
)

VALID_REVIEW_TYPES = {"contradiction", "duplicate", "missing-page", "suggestion", "confirm"}


@dataclass
class ParsedReviewBlock:
    type: str
    title: str
    description: str = ""
    options: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    search: list[str] = field(default_factory=list)


def parse_review_blocks(raw: str) -> list[ParsedReviewBlock]:
    """解析 LLM 输出中的 ---REVIEW: ... ---END REVIEW--- 块"""
    results = []

    for match in REVIEW_BLOCK_RE.finditer(raw):
        review_type = match.group(1).lower()
        title = match.group(2).strip()
        body = match.group(3).strip()

        # 类型校验，不匹配则降级为 confirm
        if review_type not in VALID_REVIEW_TYPES:
            review_type = "confirm"

        # 解析 OPTIONS / PAGES / SEARCH
        options = []
        pages = []
        search = []

        for line in body.split("\n"):
            line = line.strip()
            if line.upper().startswith("OPTIONS:"):
                opts_str = line[len("OPTIONS:"):].strip()
                options = [o.strip() for o in opts_str.split("|") if o.strip()]
            elif line.upper().startswith("PAGES:"):
                pages_str = line[len("PAGES:"):].strip()
                pages = [p.strip() for p in pages_str.split(",") if p.strip()]
            elif line.upper().startswith("SEARCH:"):
                search_str = line[len("SEARCH:"):].strip()
                search = [s.strip() for s in search_str.split("|") if s.strip()]

        # 描述 = body 中去除 OPTIONS/PAGES/SEARCH 行
        desc_lines = []
        for line in body.split("\n"):
            stripped = line.strip().upper()
            if not (stripped.startswith("OPTIONS:") or stripped.startswith("PAGES:") or stripped.startswith("SEARCH:")):
                desc_lines.append(line.strip())

        results.append(ParsedReviewBlock(
            type=review_type,
            title=title,
            description="\n".join(desc_lines).strip(),
            options=options,
            pages=pages,
            search=search,
        ))

    return results
