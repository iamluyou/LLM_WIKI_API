"""页面三层合并逻辑，对齐桌面版 page-merge.ts

第1层: Frontmatter 数组字段 Union 合并
第2层: Body 正文 LLM 合并
第3层: 锁定字段强制回写
"""

import os
import re
from datetime import date
from typing import Optional, Callable

from app.parsers.frontmatter import parse_frontmatter, set_frontmatter_field
from app.safety.language_guard import content_matches_target_language

UNION_FIELDS = ["sources", "tags", "related"]
LOCKED_FIELDS = ["type", "title", "created"]
BODY_SHRINK_THRESHOLD = 0.7


def _union_arrays(existing: list, incoming: list) -> list:
    """合并两个数组，去重保序"""
    seen = set()
    result = []
    for item in existing + incoming:
        key = str(item).lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def merge_frontmatter_arrays(
    existing_fm: dict, incoming_fm: dict
) -> dict:
    """第1层: Union 合并数组字段"""
    merged = dict(incoming_fm)  # 以 incoming 为基础
    for field in UNION_FIELDS:
        existing_vals = existing_fm.get(field, [])
        incoming_vals = incoming_fm.get(field, [])
        if isinstance(existing_vals, list) and isinstance(incoming_vals, list):
            merged[field] = _union_arrays(existing_vals, incoming_vals)
        elif isinstance(existing_vals, list):
            merged[field] = existing_vals
    return merged


def merge_page_content(
    new_content: str,
    existing_content: Optional[str],
    merger_fn: Optional[Callable] = None,
    source_file_name: str = "",
    backup_fn: Optional[Callable] = None,
    target_lang: str = "Chinese",
) -> tuple[str, bool]:
    """三层合并逻辑

    返回 (merged_content, was_merged_via_llm)
    """
    # 快速路径：全新页面
    if existing_content is None:
        return new_content, False

    # 快速路径：字节级相同
    if new_content == existing_content:
        return existing_content, False

    # 解析 frontmatter
    existing_fm, existing_body = parse_frontmatter(existing_content)
    incoming_fm, incoming_body = parse_frontmatter(new_content)

    # 第1层: Union 合并数组字段
    merged_fm = merge_frontmatter_arrays(existing_fm, incoming_fm)

    # 检查是否仅数组字段不同
    if existing_body.strip() == incoming_body.strip():
        return _rebuild_page(merged_fm, incoming_body), False

    # 第2层: LLM 合并 body
    was_llm_merged = False
    if merger_fn:
        try:
            merged_text = merger_fn(existing_content, new_content, source_file_name)
            # 健全性检查
            merged_fm_check, merged_body = parse_frontmatter(merged_text)

            # 检查1: frontmatter 存在性
            if not merged_fm_check:
                raise ValueError("Merged output missing frontmatter")

            # 检查2: body 缩短阈值
            max_len = max(len(existing_body), len(incoming_body))
            if max_len > 0 and len(merged_body) < max_len * BODY_SHRINK_THRESHOLD:
                raise ValueError("Merged body too short, possible truncation")

            # 第1层 再次 union（防止 LLM 遗漏）
            merged_fm = merge_frontmatter_arrays(existing_fm, merged_fm_check)
            was_llm_merged = True
            result = _rebuild_page(merged_fm, merged_body)

        except Exception:
            # Fallback: 数组合并 + 新内容 body
            if backup_fn:
                try:
                    backup_fn(existing_content)
                except Exception:
                    pass
            result = _rebuild_page(merged_fm, incoming_body)
    else:
        # 无 merger_fn，直接使用数组合并 + 新 body
        result = _rebuild_page(merged_fm, incoming_body)

    # 第3层: 锁定字段强制回写
    for field in LOCKED_FIELDS:
        if field in existing_fm and existing_fm[field]:
            result = set_frontmatter_field(result, field, str(existing_fm[field]))

    # 更新 updated 为当天
    result = set_frontmatter_field(result, "updated", date.today().isoformat())

    return result, was_llm_merged


def _rebuild_page(frontmatter_dict: dict, body: str) -> str:
    """从 frontmatter 字典和 body 重建完整页面"""
    lines = ["---"]
    for key, value in frontmatter_dict.items():
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(str(v) for v in value)}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append(body)
    return "\n".join(lines)


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
