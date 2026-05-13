"""LLM 输出清洗，对齐桌面版 ingest-sanitize.ts

在写入前清洗 LLM 生成的页面内容，修复三种常见的格式问题：
1. 外层代码围栏 (```yaml ... ```)
2. frontmatter: 前缀
3. frontmatter 中的 wikilink 列表格式

官方审计：67 个实体页面中 30 个有不可严格解析的 frontmatter。
"""

import re


def sanitize_ingested_content(content: str) -> str:
    """清洗 LLM 生成的 wiki 页面内容"""
    cleaned = content

    # (1) 剥离外层代码围栏
    cleaned = _strip_outer_code_fence(cleaned)

    # (2) 剥离 frontmatter: 前缀
    cleaned = _strip_frontmatter_key_prefix(cleaned)

    # (3) 修复 frontmatter 中的 wikilink 列表
    cleaned = _repair_wikilink_lists(cleaned)

    return cleaned


def _strip_outer_code_fence(content: str) -> str:
    """剥离包裹整个文档的外层代码围栏

    只在首行是开围栏、末行是闭围栏时才剥离。
    """
    open_match = re.match(r'^[ \t]*```(?:yaml|md|markdown)?[ \t]*\r?\n', content)
    if not open_match:
        return content
    after_open = content[open_match.end():]

    close_match = re.search(r'\r?\n[ \t]*```[ \t]*\r?\n?\s*$', after_open)
    if not close_match:
        return content
    return after_open[:close_match.start()]


def _strip_frontmatter_key_prefix(content: str) -> str:
    """剥离 frontmatter: 前缀行

    有些 LLM 会在 --- 前加一个 `frontmatter:` 键名
    """
    m = re.match(r'^[ \t]*frontmatter\s*:\s*\r?\n(?=[ \t]*---\s*\r?\n)', content)
    if not m:
        return content
    return content[m.end():]


def _repair_wikilink_lists(content: str) -> str:
    """修复 frontmatter 中的 wikilink 列表格式

    将 `related: [[a]], [[b]], [[c]]` 转为 `related: ["[[a]]", "[[b]]", "[[c]]"]`
    只修改 frontmatter 区域内的行
    """
    fm_match = re.match(r'^(---\s*\r?\n)([\s\S]*?)(\r?\n---\s*(\r?\n|$))', content)
    if not fm_match:
        return content

    open_delim = fm_match.group(1)
    fm_body = fm_match.group(2)
    close_delim = fm_match.group(3)
    rest = content[fm_match.end():]

    repaired_lines = []
    for line in fm_body.split('\n'):
        lm = re.match(
            r'^(\s*[A-Za-z_][\w-]*\s*:\s*)(\[\[[^\]]+\]\](?:\s*,\s*\[\[[^\]]+\]\])+)\s*$',
            line,
        )
        if lm:
            prefix = lm.group(1)
            items_str = lm.group(2)
            items = [f'"{s.strip()}"' for s in items_str.split(',') if s.strip()]
            repaired_lines.append(f'{prefix}[{", ".join(items)}]')
        else:
            repaired_lines.append(line)

    return open_delim + '\n'.join(repaired_lines) + close_delim + rest
