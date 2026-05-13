"""端到端 Ingest 集成测试 — mock LLM，几秒内跑完管道

验证目标：
1. index.md / overview.md 直接覆盖（对齐官方 listing pages 策略）
2. 普通页面合并（新建 + 已有页面合并）
3. log.md 追加
4. 缓存保存
5. Task progress 更新
6. 返回结果结构正确
"""

import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.ingest_engine import _ingest_one, run_ingest
from app.services.wiki_manager import WikiManager
from app.services.task_queue import Task
from app.models.wiki import TaskResult


# --- Mock LLM 输出 ---

MOCK_ANALYSIS_RESULT = "## Analysis\n\nKey entities: TestEntity, TestConcept"

MOCK_GENERATION_RESULT = """\
---FILE: wiki/entities/test-entity.md---
---
type: entity
title: Test Entity
tags: [test]
related: []
created: 2026-05-13
updated: 2026-05-13
sources: ["test-source.md"]
---
# Test Entity

A test entity.
---END FILE---

---FILE: wiki/concepts/test-concept.md---
---
type: concept
title: Test Concept
tags: [test]
related: []
created: 2026-05-13
updated: 2026-05-13
sources: ["test-source.md"]
---
# Test Concept

A test concept.
---END FILE---

---FILE: wiki/index.md---
# Wiki Index

## Entities
- [[test-entity]] — Test entity

## Concepts
- [[test-concept]] — Test concept
---END FILE---

---FILE: wiki/overview.md---
---
type: overview
title: Overview
created: 2026-05-13
updated: 2026-05-13
tags: []
related: []
sources: []
---
# Overview

Project overview with [[test-entity]] and [[test-concept]].
---END FILE---

---FILE: wiki/log.md---
- 2026-05-13: Ingested test-source.md
---END FILE---
"""

MOCK_MERGE_RESULT = """\
---
type: entity
title: Test Entity
created: 2026-05-13
updated: 2026-05-13
tags: [test]
related: []
sources: ["test-source.md"]
---
# Test Entity

Merged content with old and new info.
"""


@pytest.fixture
def temp_wiki(tmp_path):
    """创建临时 wiki 目录结构"""
    wiki_root = str(tmp_path)
    for d in [
        "wiki/entities", "wiki/concepts", "wiki/sources",
        "raw/sources", "raw/assets",
        ".llm-wiki/page-history", ".llm-wiki/ingest-cache",
    ]:
        os.makedirs(os.path.join(wiki_root, d), exist_ok=True)

    # 写入必要的上下文文件
    with open(os.path.join(wiki_root, "purpose.md"), "w") as f:
        f.write("# Purpose\n\nTest wiki purpose.")
    with open(os.path.join(wiki_root, "schema.md"), "w") as f:
        f.write("# Schema\n\nPage types: entity, concept")
    with open(os.path.join(wiki_root, "wiki", "index.md"), "w") as f:
        f.write("# Wiki Index\n\n<!-- existing index -->\n")
    with open(os.path.join(wiki_root, "wiki", "overview.md"), "w") as f:
        f.write("---\ntype: overview\ntitle: Overview\n---\n\n# Overview\n\nExisting overview.\n")
    with open(os.path.join(wiki_root, "wiki", "log.md"), "w") as f:
        f.write("# Log\n")

    return wiki_root


def _make_mock_achat(responses):
    """创建按顺序返回的 mock achat"""
    call_count = 0

    async def mock_achat(messages, **kwargs):
        nonlocal call_count
        idx = min(call_count, len(responses) - 1)
        call_count += 1
        text, usage = responses[idx]
        return text, usage

    return mock_achat


class TestIngestE2E:
    """端到端管道测试"""

    @pytest.mark.asyncio
    async def test_ingest_one_creates_pages_and_overwrites_index(self, temp_wiki):
        """验证 _ingest_one: 新建页面、覆盖 index/overview、追加 log"""
        wm = WikiManager(wiki_root=temp_wiki)

        # 对齐官方：index/overview 直接覆盖，只需 analysis + generation 两次 LLM 调用
        llm_responses = [
            (MOCK_ANALYSIS_RESULT, {"input": 100, "output": 50}),
            (MOCK_GENERATION_RESULT, {"input": 200, "output": 300}),
        ]
        mock_achat = _make_mock_achat(llm_responses)

        task = Task("test-task", ["test-source"])

        with patch("app.services.ingest_engine.wiki_manager", wm), \
             patch("app.services.ingest_engine.llm_client") as mock_llm, \
             patch("app.services.ingest_engine.settings") as mock_settings, \
             patch("app.services.ingest_engine.content_matches_target_language", return_value=True):

            mock_llm.achat = mock_achat
            mock_settings.output_language = "Chinese"
            mock_settings.ingest_cache_enabled = False
            mock_settings.wiki_root = temp_wiki

            pages_created, pages_updated, pages_merged, tokens = await _ingest_one(
                "test-source.md", "# Test Source\n\nContent", task
            )

        # 验证新建页面
        assert "entities/test-entity.md" in pages_created
        assert "concepts/test-concept.md" in pages_created

        # 验证 index/overview 是 updated（直接覆盖，对齐官方）
        assert "index.md" in pages_updated
        assert "overview.md" in pages_updated

        # 验证 log.md 追加
        assert "log.md" in pages_updated

        # 验证 index.md 不是空的
        index_content = wm.read_wiki_page("index.md")
        assert "test-entity" in index_content
        assert "test-concept" in index_content

        # 验证 overview.md 被覆盖（不再是旧内容）
        overview_content = wm.read_wiki_page("overview.md")
        assert "test-entity" in overview_content

        # 验证 tokens 统计
        assert tokens["input"] > 0
        assert tokens["output"] > 0

    @pytest.mark.asyncio
    async def test_ingest_one_merges_existing_page(self, temp_wiki):
        """验证已有页面走合并路径（LLM merge）"""
        wm = WikiManager(wiki_root=temp_wiki)

        # 先创建一个已有页面
        wm.write_wiki_page("entities/test-entity.md",
            "---\ntype: entity\ntitle: Test Entity\ntags: [test]\nrelated: []\n"
            "created: 2026-05-13\nupdated: 2026-05-13\nsources: []\n---\n"
            "# Test Entity\n\nOld content.\n"
        )

        llm_responses = [
            (MOCK_ANALYSIS_RESULT, {"input": 100, "output": 50}),
            (MOCK_GENERATION_RESULT, {"input": 200, "output": 300}),
            # entity merge（index/overview 不再合并，直接覆盖）
            (MOCK_MERGE_RESULT, {"input": 50, "output": 80}),
        ]
        mock_achat = _make_mock_achat(llm_responses)

        task = Task("test-task", ["test-source"])

        with patch("app.services.ingest_engine.wiki_manager", wm), \
             patch("app.services.ingest_engine.llm_client") as mock_llm, \
             patch("app.services.ingest_engine.settings") as mock_settings, \
             patch("app.services.ingest_engine.content_matches_target_language", return_value=True):

            mock_llm.achat = mock_achat
            mock_settings.output_language = "Chinese"
            mock_settings.ingest_cache_enabled = False
            mock_settings.wiki_root = temp_wiki

            pages_created, pages_updated, pages_merged, tokens = await _ingest_one(
                "test-source.md", "# Test Source\n\nContent", task
            )

        # test-entity.md 应该是 updated（合并），不是 created
        assert "entities/test-entity.md" not in pages_created
        assert "entities/test-entity.md" in pages_updated
        assert pages_merged >= 1  # 至少 1 次 LLM 合并

    @pytest.mark.asyncio
    async def test_run_ingest_full_pipeline(self, temp_wiki):
        """验证 run_ingest 完整流程：缓存检查 + _ingest_one + 缓存保存"""
        wm = WikiManager(wiki_root=temp_wiki)

        # 写入 raw source
        wm.write_raw_source("test-source.md", "# Test Source\n\nContent")

        llm_responses = [
            (MOCK_ANALYSIS_RESULT, {"input": 100, "output": 50}),
            (MOCK_GENERATION_RESULT, {"input": 200, "output": 300}),
        ]
        mock_achat = _make_mock_achat(llm_responses)

        task = Task("test-task", ["test-source"])

        with patch("app.services.ingest_engine.wiki_manager", wm), \
             patch("app.services.ingest_engine.llm_client") as mock_llm, \
             patch("app.services.ingest_engine.settings") as mock_settings, \
             patch("app.services.ingest_engine.ProjectLock") as mock_lock, \
             patch("app.services.ingest_engine.content_matches_target_language", return_value=True):

            mock_llm.achat = mock_achat
            mock_settings.output_language = "Chinese"
            mock_settings.ingest_cache_enabled = False
            mock_settings.wiki_root = temp_wiki
            mock_lock.return_value.__enter__ = MagicMock(return_value=None)
            mock_lock.return_value.__exit__ = MagicMock(return_value=False)

            result = await run_ingest(["test-source"], task)

        assert isinstance(result, TaskResult)
        assert result.cache_hit is False
        assert len(result.pages_created) >= 2
        assert len(result.pages_updated) >= 2  # index + overview + log
        assert result.tokens_used["input"] > 0

    @pytest.mark.asyncio
    async def test_task_progress_updates(self, temp_wiki):
        """验证 Task progress 在各步骤正确更新"""
        wm = WikiManager(wiki_root=temp_wiki)
        progress_history = []

        class TrackingTask(Task):
            def update_progress(self, progress: str):
                progress_history.append(progress)
                super().update_progress(progress)

        task = TrackingTask("test-task", ["test-source"])

        llm_responses = [
            (MOCK_ANALYSIS_RESULT, {"input": 100, "output": 50}),
        ]
        mock_achat = _make_mock_achat(llm_responses)

        with patch("app.services.ingest_engine.wiki_manager", wm), \
             patch("app.services.ingest_engine.llm_client") as mock_llm, \
             patch("app.services.ingest_engine.settings") as mock_settings, \
             patch("app.services.ingest_engine.content_matches_target_language", return_value=True):

            mock_llm.achat = mock_achat
            mock_settings.output_language = "Chinese"
            mock_settings.ingest_cache_enabled = False
            mock_settings.wiki_root = temp_wiki

            try:
                await _ingest_one("test-source.md", "# Content", task)
            except Exception:
                pass  # generation 可能返回不够内容，但 progress 已记录

        assert any("Analyzing" in p for p in progress_history)
