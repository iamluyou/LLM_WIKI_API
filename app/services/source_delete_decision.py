"""Source 删除时的页面决策逻辑，对齐桌面版 source-delete-decision.ts

纯函数，无副作用，便于单元测试。
"""

from typing import List, Optional


def decide_page_fate(
    frontmatter_sources: List[str],
    deleting_source: str,
) -> dict:
    """判断一个 wiki 页面在删除 source 后的命运

    对齐桌面版 decidePageFate()，三路决策：
    - skip:   页面来源中不包含被删 source（误匹配防护）
    - keep:   页面还有其他来源支撑，保留但更新 sources 列表
    - delete: 被删 source 是该页面唯一来源，页面应随之删除

    Returns:
        {"action": "skip"|"keep"|"delete", "updated_sources": [...], "reason": "..."}
    """
    deleting_lower = deleting_source.lower()

    # 在 frontmatter_sources 中查找（大小写不敏感）
    matched_idx = None
    for i, src in enumerate(frontmatter_sources):
        if src.lower() == deleting_lower:
            matched_idx = i
            break

    if matched_idx is None:
        return {
            "action": "skip",
            "updated_sources": frontmatter_sources,
            "reason": f'page sources do not include "{deleting_source}"',
        }

    # 过滤掉该 source，得到 survivors
    survivors = [
        src for i, src in enumerate(frontmatter_sources)
        if i != matched_idx
    ]

    if len(survivors) > 0:
        return {
            "action": "keep",
            "updated_sources": survivors,
            "reason": "",
        }

    return {
        "action": "delete",
        "updated_sources": [],
        "reason": "",
    }
