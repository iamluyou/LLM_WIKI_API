"""Frontmatter 严格解析与 Pydantic 校验，对齐桌面版 frontmatter.ts"""

import re
from datetime import date
from typing import Optional

import frontmatter
from pydantic import ValidationError

from app.models.wiki import (
    WikiFrontmatter,
    SourceFrontmatter,
    ThesisFrontmatter,
    FindingFrontmatter,
    PageType,
)


# 类型到 Pydantic model 映射
FRONTMATTER_MODELS = {
    "source": SourceFrontmatter,
    "thesis": ThesisFrontmatter,
    "finding": FindingFrontmatter,
}


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 frontmatter，返回 (metadata, body)"""
    try:
        post = frontmatter.loads(content)
        return dict(post.metadata), post.content
    except Exception:
        return {}, content


def validate_frontmatter(metadata: dict) -> tuple[Optional[WikiFrontmatter], list[str]]:
    """校验 frontmatter 是否符合 schema

    返回 (validated_model, errors)
    """
    errors = []

    # 基本字段检查
    required_fields = ["type", "title", "created", "updated"]
    for f in required_fields:
        if f not in metadata:
            errors.append(f"Missing required field: {f}")

    if errors:
        return None, errors

    page_type = metadata.get("type", "")
    if page_type not in {t.value for t in PageType}:
        errors.append(f"Invalid page type: {page_type}")

    if errors:
        return None, errors

    # 选择对应的 Pydantic model
    model_cls = FRONTMATTER_MODELS.get(page_type, WikiFrontmatter)

    try:
        # 日期字符串转换
        for field in ("created", "updated"):
            val = metadata.get(field)
            if isinstance(val, str):
                try:
                    metadata[field] = date.fromisoformat(val)
                except ValueError:
                    errors.append(f"Invalid date format for {field}: {val}")

        if errors:
            return None, errors

        validated = model_cls(**metadata)
        return validated, []
    except ValidationError as e:
        for err in e.errors():
            errors.append(f"{err['loc']}: {err['msg']}")
        return None, errors


def extract_frontmatter_raw(content: str) -> Optional[str]:
    """提取原始 frontmatter 文本（不解析）"""
    match = re.match(r"^---\n([\s\S]*?)\n---", content)
    if match:
        return match.group(1)
    return None


def set_frontmatter_field(content: str, field_name: str, value: str) -> str:
    """替换或追加 frontmatter 标量字段，保持文档其余部分不变

    对齐桌面版 setFrontmatterScalar
    """
    fm_raw = extract_frontmatter_raw(content)
    if fm_raw is None:
        return content

    # 尝试替换已有字段
    field_pattern = re.compile(rf"^{re.escape(field_name)}:\s*.*$", re.MULTILINE)
    if field_pattern.search(fm_raw):
        new_fm = field_pattern.sub(f"{field_name}: {value}", fm_raw)
    else:
        new_fm = fm_raw.rstrip() + f"\n{field_name}: {value}"

    # 替换原始内容中的 frontmatter
    new_content = re.sub(
        r"^---\n[\s\S]*?\n---",
        f"---\n{new_fm}\n---",
        content,
        count=1,
    )
    return new_content
