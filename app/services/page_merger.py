"""页面三层合并逻辑，对齐桌面版 page-merge.ts

第1层: Frontmatter 数组字段 Union 合并（直接操作文本）
第2层: Body 正文 LLM 合并
第3层: 锁定字段强制回写

对齐官方关键差异：
- merger_fn 接收的是第1层合并后的内容（arrayMerged），而非原始 new_content
- 数组合并使用直接文本操作，而非 dict 重建
- body 相同时跳过 LLM 调用
"""

import os
import re
from datetime import date
from typing import Optional, Callable

from app.parsers.frontmatter import parse_frontmatter, set_frontmatter_field

UNION_FIELDS = ["sources", "tags", "related"]
LOCKED_FIELDS = ["type", "title", "created"]
BODY_SHRINK_THRESHOLD = 0.7


def _parse_frontmatter_array(content: str, field_name: str) -> list[str]:
    """从 frontmatter 中提取数组字段值

    对齐官方 parseFrontmatterArray，支持两种格式：
    - inline 形式: name: ["a", "b"] 或 name: [a, b]
    - block 形式:  name:\\n  - a\\n  - b
    """
    fm_match = re.match(r'^---\n([\s\S]*?)\n---', content)
    if not fm_match:
        return []
    fm = fm_match.group(1)
    escaped_name = re.escape(field_name)

    # block form: name:\n  - a\n  - b
    block_re = re.compile(
        rf'^{escaped_name}:\s*\n((?:[ \t]+-\s+.+\n?)+)', re.MULTILINE
    )
    block = block_re.search(fm)
    if block:
        out: list[str] = []
        for line in block.group(1).split("\n"):
            m = re.match(r'^\s+-\s+["\']?(.+?)["\']?\s*$', line)
            if m and m.group(1):
                out.append(m.group(1).strip())
        return out

    # inline form: name: [a, b]
    inline_re = re.compile(rf'^{escaped_name}:\s*\[([^\]]*)\]', re.MULTILINE)
    m = inline_re.search(fm)
    if not m:
        return []
    body = m.group(1).strip()
    if not body:
        return []
    return [s.strip().strip('"').strip("'") for s in body.split(",") if s.strip()]


def _write_frontmatter_array(content: str, field_name: str, values: list[str]) -> str:
    """重写 frontmatter 中的数组字段为 inline 形式

    对齐官方 writeFrontmatterArray：
    - 替换 inline form: name: [...] → name: [...]
    - 替换 block form:  name:\\n  - a → name: [...]
    - 字段不存在时追加
    - 统一输出 inline 形式
    """
    fm_match = re.match(r'^(---\n)([\s\S]*?)(\n---)', content)
    if not fm_match:
        return content
    open_delim, fm_body, close_delim = fm_match.group(1), fm_match.group(2), fm_match.group(3)
    rest = content[fm_match.end():]

    escaped_name = re.escape(field_name)
    serialized = ", ".join(f'"{v}"' for v in values)
    new_line = f"{field_name}: [{serialized}]"

    # 替换 inline form
    inline_re = re.compile(rf'^{escaped_name}:\s*\[[^\]]*\]', re.MULTILINE)
    if inline_re.search(fm_body):
        new_fm_body = inline_re.sub(new_line, fm_body)
        return f"{open_delim}{new_fm_body}{close_delim}{rest}"

    # 替换 block form
    block_re = re.compile(
        rf'^{escaped_name}:\s*\n(?:[ \t]+-\s+.+\n?)+', re.MULTILINE
    )
    if block_re.search(fm_body):
        new_fm_body = block_re.sub(new_line, fm_body)
        return f"{open_delim}{new_fm_body}{close_delim}{rest}"

    # 字段不存在 — 追加
    new_fm_body = fm_body.rstrip() + "\n" + new_line
    return f"{open_delim}{new_fm_body}{close_delim}{rest}"


def _merge_lists(existing: list[str], incoming: list[str]) -> list[str]:
    """合并两个列表，大小写不敏感去重，首次出现的命名优先"""
    seen: set[str] = set()
    result: list[str] = []
    for s in existing + incoming:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            result.append(s)
    return result


def merge_array_fields_into_content(
    new_content: str,
    existing_content: Optional[str],
    fields: list[str] = None,
) -> str:
    """第1层: 对齐官方 mergeArrayFieldsIntoContent

    直接在文本上操作 frontmatter 数组字段的 union 合并，
    保留原始文档结构，不重建。
    """
    if fields is None:
        fields = list(UNION_FIELDS)
    if not existing_content:
        return new_content
    if not re.match(r'^---\n', existing_content):
        return new_content

    result = new_content
    changed = False
    for field in fields:
        old_values = _parse_frontmatter_array(existing_content, field)
        if not old_values:
            continue
        new_values = _parse_frontmatter_array(result, field)
        merged = _merge_lists(old_values, new_values)
        if merged == new_values:
            continue
        result = _write_frontmatter_array(result, field, merged)
        changed = True

    return result if changed else new_content


async def merge_page_content(
    new_content: str,
    existing_content: Optional[str],
    merger_fn: Optional[Callable] = None,
    source_file_name: str = "",
    backup_fn: Optional[Callable] = None,
    target_lang: str = "Chinese",
) -> tuple[str, bool]:
    """三层合并逻辑，对齐官方 page-merge.ts

    返回 (merged_content, was_merged_via_llm)
    """
    # 快速路径：全新页面
    if existing_content is None:
        return new_content, False

    # 快速路径：字节级相同
    if new_content == existing_content:
        return existing_content, False

    # 第1层: Union 合并数组字段（直接文本操作）
    array_merged = merge_array_fields_into_content(new_content, existing_content)

    # 快速路径：body 相同（仅 frontmatter 数组字段不同）
    _, old_body = parse_frontmatter(existing_content)
    _, array_merged_body = parse_frontmatter(array_merged)
    if old_body.strip() == array_merged_body.strip():
        return array_merged, False

    # 第2层: LLM 合并 body
    was_llm_merged = False
    if merger_fn:
        try:
            # 对齐官方：merger_fn 接收第1层合并后的内容
            merged_text = await merger_fn(existing_content, array_merged, source_file_name)
            # 健全性检查
            merged_fm_check, merged_body = parse_frontmatter(merged_text)

            # 检查1: frontmatter 存在性
            if not merged_fm_check:
                raise ValueError("Merged output missing frontmatter")

            # 检查2: body 缩短阈值
            _, incoming_body = parse_frontmatter(array_merged)
            max_len = max(len(old_body), len(incoming_body))
            if max_len > 0 and len(merged_body) < max_len * BODY_SHRINK_THRESHOLD:
                raise ValueError("Merged body too short, possible truncation")

            was_llm_merged = True
            result = merged_text

            # 第1层再次 union（防止 LLM 遗漏）
            result = merge_array_fields_into_content(result, array_merged)

        except Exception:
            # Fallback: 数组合并 + 新内容 body
            if backup_fn:
                try:
                    backup_fn(existing_content)
                except Exception:
                    pass
            result = array_merged
    else:
        # 无 merger_fn，直接使用数组合并后的内容
        result = array_merged

    # 第3层: 锁定字段强制回写
    existing_fm, _ = parse_frontmatter(existing_content)
    for field in LOCKED_FIELDS:
        existing_value = existing_fm.get(field)
        if isinstance(existing_value, str) and existing_value:
            result = set_frontmatter_field(result, field, str(existing_value))

    # 更新 updated 为当天
    result = set_frontmatter_field(result, "updated", date.today().isoformat())

    return result, was_llm_merged


def backup_page(wiki_root: str, rel_path: str, existing_content: str) -> None:
    """合并前备份，对齐桌面版 backupExistingPage

    best-effort，错误不阻塞主流程
    """
    try:
        backup_dir = os.path.join(wiki_root, ".llm-wiki", "page-history")
        os.makedirs(backup_dir, exist_ok=True)
        safe_name = rel_path.replace(os.sep, "_").replace("/", "_")
        timestamp = date.today().isoformat()
        backup_path = os.path.join(backup_dir, f"{safe_name}-{timestamp}.md")
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(existing_content)
    except Exception:
        pass  # best-effort
