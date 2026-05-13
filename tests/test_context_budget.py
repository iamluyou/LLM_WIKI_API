"""单元测试：上下文预算分配，对齐官方 context-budget.test.ts"""

import pytest
from app.services.context_budget import compute_context_budget, DEFAULT_MAX_CTX


class TestComputeContextBudget:
    def test_default_budget(self):
        budget = compute_context_budget(0)
        assert budget.max_ctx == DEFAULT_MAX_CTX
        assert budget.response_reserve == int(DEFAULT_MAX_CTX * 0.15)
        assert budget.index_budget == int(DEFAULT_MAX_CTX * 0.05)
        assert budget.page_budget == int(DEFAULT_MAX_CTX * 0.5)

    def test_custom_budget(self):
        budget = compute_context_budget(100000)
        assert budget.max_ctx == 100000
        assert budget.page_budget == 50000

    def test_per_page_size(self):
        budget = compute_context_budget(DEFAULT_MAX_CTX)
        # max(5000, floor(pageBudget * 0.3))
        expected = min(budget.page_budget, max(5000, int(budget.page_budget * 0.3)))
        assert budget.max_page_size == expected

    def test_tiny_context(self):
        budget = compute_context_budget(10000)
        # page_budget = 5000, max_page_size = min(5000, max(5000, 1500)) = 5000
        assert budget.max_page_size == 5000

    def test_large_context(self):
        budget = compute_context_budget(1_000_000)
        assert budget.page_budget == 500_000
        # max(5000, 500000*0.3=150000) = 150000
        assert budget.max_page_size == 150_000

    def test_none_context(self):
        budget = compute_context_budget(0)
        assert budget.max_ctx == DEFAULT_MAX_CTX

    def test_negative_context(self):
        budget = compute_context_budget(-1)
        assert budget.max_ctx == DEFAULT_MAX_CTX
