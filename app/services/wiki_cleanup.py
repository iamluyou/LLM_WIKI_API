"""Wiki 清理工具，对齐桌面版 wiki-cleanup.ts

处理页面删除后的善后：index 条目清理、死 wikilink 替换、frontmatter 数组清理。
纯字符串操作，无 IO 副作用。
"""

import re
from typing import List, Set


def normalize_wiki_ref_key(s: str) -> str:
    """归一化 wiki 引用键，对齐桌面版 normalizeWikiRefKey()

    消除两种变异轴：大小写 + 分隔符（空格/连字符/下划线）。

    "KV Cache" → "kvcache"
    "kv-cache" → "kvcache"
    "kv_cache" → "kvcache"
    "wiki/concepts/kv-cache.md" → "kvcache"
    """
    # trim
    s = s.strip()
    # 反斜杠转正斜杠
    s = s.replace("\\", "/")
    # 取最后一段（leaf）
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    # 去 .md 后缀
    if s.endswith(".md"):
        s = s[:-3]
    # 小写
    s = s.lower()
    # 去除空格、连字符、下划线
    s = re.sub(r"[\s\-_]+", "", s)
    return s


class DeletedPageInfo:
    """被删除页面的元信息，对齐桌面版 DeletedPageInfo"""

    def __init__(self, slug: str, title: str = ""):
        self.slug = slug
        self.title = title


def build_deleted_keys(infos: List[DeletedPageInfo]) -> Set[str]:
    """构建归一化键集合，对齐桌面版 buildDeletedKeys()

    同时收录 slug 和 title 两种形式的归一化键。
    """
    keys = set()
    for info in infos:
        keys.add(normalize_wiki_ref_key(info.slug))
        if info.title:
            keys.add(normalize_wiki_ref_key(info.title))
    return keys


def extract_frontmatter_title(content: str) -> str:
    """从 YAML frontmatter 中提取 title 值，对齐桌面版 extractFrontmatterTitle()"""
    m = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def clean_index_listing(text: str, deleted_keys: Set[str]) -> str:
    """从索引式文件中删除主 wikilink 指向已删页面的列表项

    对齐桌面版 cleanIndexListing()，结构化匹配，非子串匹配。

    匹配格式：- [[Target]] 描述  或  * [[T|D]]
    """
    if not deleted_keys:
        return text

    lines = text.split("\n")
    result = []
    # 匹配列表项中的主 wikilink：- [[Target]] 或 * [[Target|alias]]
    pattern = re.compile(r"^\s*[-*]\s*\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")

    for line in lines:
        m = pattern.match(line)
        if m:
            target = m.group(1).strip()
            if normalize_wiki_ref_key(target) in deleted_keys:
                continue  # 过滤掉
        result.append(line)

    return "\n".join(result)


def strip_deleted_wikilinks(text: str, deleted_keys: Set[str]) -> str:
    """将指向已删页面的 wikilink 转为纯文本，对齐桌面版 stripDeletedWikilinks()

    [[deleted]]       → deleted
    [[deleted|alias]] → alias
    [[kept]]          → [[kept]]（不变）
    """
    if not deleted_keys:
        return text

    def replace_wikilink(m: re.Match) -> str:
        target = m.group(1).strip()
        alias = m.group(2)  # 可能为 None
        if normalize_wiki_ref_key(target) in deleted_keys:
            return alias if alias else target
        return m.group(0)  # 保持原样

    pattern = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]")
    return pattern.sub(replace_wikilink, text)


def write_frontmatter_array(content: str, field_name: str, values: List[str]) -> str:
    """重写 frontmatter 中的数组字段，对齐桌面版 writeFrontmatterArray()

    仅修改指定字段，保留其余 frontmatter 和正文不变。
    """
    if not values:
        # 写入空数组
        new_value = f"{field_name}: []"
    else:
        # YAML 数组格式
        lines = [f"{field_name}:"]
        for v in values:
            # 对含特殊字符的值加引号
            if any(c in v for c in [":", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`"]):
                escaped = v.replace('"', '\\"')
                lines.append(f'  - "{escaped}"')
            else:
                lines.append(f"  - {v}")
        new_value = "\n".join(lines)

    # 尝试替换已有字段（包括多行数组格式）
    # 匹配字段行到下一个非列表项行或字段行
    field_pattern = re.compile(
        rf"^{re.escape(field_name)}:\s*(?:\[.*\]|\n(?:\s+-\s+.*(?:\n|$))*)",
        re.MULTILINE,
    )

    fm_match = re.match(r"^---\n([\s\S]*?)\n---", content)
    if fm_match is None:
        return content

    fm_raw = fm_match.group(1)

    if field_pattern.search(fm_raw):
        new_fm = field_pattern.sub(new_value, fm_raw)
    else:
        new_fm = fm_raw.rstrip() + "\n" + new_value

    new_content = re.sub(
        r"^---\n[\s\S]*?\n---",
        f"---\n{new_fm}\n---",
        content,
        count=1,
    )
    return new_content


def parse_frontmatter_array(content: str, field_name: str) -> List[str]:
    """从 frontmatter 中解析数组字段，返回元素列表"""
    fm_match = re.match(r"^---\n([\s\S]*?)\n---", content)
    if fm_match is None:
        return []

    fm_raw = fm_match.group(1)

    # 内联数组格式：field: [a, b, c]
    inline_pattern = re.compile(rf"^{re.escape(field_name)}:\s*\[(.+)\]\s*$", re.MULTILINE)
    m = inline_pattern.search(fm_raw)
    if m:
        raw = m.group(1)
        # 按逗号分割，再去引号和空白
        items = []
        for part in raw.split(","):
            part = part.strip().strip('"').strip("'")
            if part:
                items.append(part)
        return items

    # 多行数组格式：field:\n  - a\n  - b
    multiline_pattern = re.compile(
        rf"^{re.escape(field_name)}:\s*\n((?:\s+-\s+.*(?:\n|$))*)",
        re.MULTILINE,
    )
    m = multiline_pattern.search(fm_raw)
    if m:
        items = re.findall(r"^\s+-\s+\"(.+?)\"|^\s+-\s+'(.+?)'|^\s+-\s+(.+)$", m.group(1), re.MULTILINE)
        return [a or b or c.strip() for a, b, c in items if a or b or c]

    return []
