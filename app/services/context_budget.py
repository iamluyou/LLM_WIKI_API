"""上下文预算分配，对齐桌面版 context-budget.ts

预算分配比例：
  ┌─────────────────────────────────────────────────────┐
  │              maxCtx (100%)                          │
  ├──────┬───────────────┬──────────────────┬───────────┤
  │ idx  │   pages       │  history + sys   │  resp     │
  │  5%  │    50%        │    ~30%          │   15%     │
  └──────┴───────────────┴──────────────────┴───────────┘
"""

from dataclasses import dataclass

DEFAULT_MAX_CTX = 204_800
RESPONSE_RESERVE_FRAC = 0.15
INDEX_BUDGET_FRAC = 0.05
PAGE_BUDGET_FRAC = 0.5
PER_PAGE_FRAC = 0.3
PER_PAGE_FLOOR = 5_000


@dataclass
class ContextBudget:
    max_ctx: int
    response_reserve: int
    index_budget: int
    page_budget: int
    max_page_size: int


def compute_context_budget(max_context_size: int = 0) -> ContextBudget:
    """根据 LLM 上下文窗口计算字符预算（对齐官方 computeContextBudget）

    Args:
        max_context_size: LLM 最大上下文字符数，0 或负数使用默认值
    """
    max_ctx = max_context_size if max_context_size > 0 else DEFAULT_MAX_CTX

    response_reserve = int(max_ctx * RESPONSE_RESERVE_FRAC)
    index_budget = int(max_ctx * INDEX_BUDGET_FRAC)
    page_budget = int(max_ctx * PAGE_BUDGET_FRAC)

    # 单页截断上限：
    #   最小 PER_PAGE_FLOOR(5000)，最大不超过 page_budget
    #   正常取 page_budget * 30%
    max_page_size = min(
        page_budget,
        max(PER_PAGE_FLOOR, int(page_budget * PER_PAGE_FRAC)),
    )

    return ContextBudget(
        max_ctx=max_ctx,
        response_reserve=response_reserve,
        index_budget=index_budget,
        page_budget=page_budget,
        max_page_size=max_page_size,
    )
