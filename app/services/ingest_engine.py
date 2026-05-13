"""Ingest 完整管道，对齐桌面版 autoIngest

流程：缓存检查 → 分析(prompt1) → 生成(prompt2) → 解析 → 安全检查 → 合并 → 写入 → 缓存保存
"""

import asyncio
import logging
import os
from typing import Optional

from app.config import settings
from app.models.wiki import TaskResult
from app.parsers.file_blocks import parse_file_blocks
from app.parsers.review_blocks import parse_review_blocks
from app.prompts.analysis import build_analysis_prompt
from app.prompts.generation import build_generation_prompt
from app.prompts.merger import build_page_merger_prompt
from app.safety.ingest_cache import ingest_cache
from app.safety.ingest_sanitize import sanitize_ingested_content
from app.safety.language_guard import content_matches_target_language
from app.safety.path_guard import is_safe_ingest_path, sanitize_path
from app.safety.project_lock import ProjectLock
from app.services.llm_client import llm_client
from app.services.page_merger import merge_page_content, backup_page
from app.services.task_queue import Task
from app.services.wiki_manager import wiki_manager

logger = logging.getLogger(__name__)


async def run_ingest(source_ids: list[str], task: Task) -> TaskResult:
    """执行 Ingest 管道（在项目锁保护下）"""
    result = TaskResult()
    total_input_tokens = 0
    total_output_tokens = 0

    logger.info(f"[Ingest] Starting ingest for {len(source_ids)} source(s): {source_ids}")

    for source_id in source_ids:
        task.update_progress(f"Processing {source_id}")
        logger.info(f"[Ingest] Processing source: {source_id}")

        # 查找 raw 文件
        raw_filename = _find_raw_file(source_id)
        if not raw_filename:
            logger.warning(f"[Ingest] Source not found: {source_id}")
            continue

        # 读取源内容
        content = wiki_manager.read_file(os.path.join("raw", "sources", raw_filename))
        if not content:
            logger.warning(f"[Ingest] Empty content for source: {raw_filename}")
            continue

        logger.info(f"[Ingest] Read source file: {raw_filename} ({len(content)} chars)")

        # 缓存检查
        if settings.ingest_cache_enabled and ingest_cache.check(raw_filename, content):
            result.cache_hit = True
            logger.info(f"[Ingest] Cache hit for {raw_filename}, skipping")
            continue

        # 项目锁保护
        with ProjectLock() as lock:
            pages_created, pages_updated, pages_merged, tokens = await _ingest_one(
                raw_filename, content, task
            )
            result.pages_created.extend(pages_created)
            result.pages_updated.extend(pages_updated)
            result.pages_merged += pages_merged
            total_input_tokens += tokens.get("input", 0)
            total_output_tokens += tokens.get("output", 0)

        logger.info(f"[Ingest] Source {raw_filename} done: {len(pages_created)} created, {len(pages_updated)} updated, {pages_merged} merged")

        # 保存缓存（无硬失败时）
        if settings.ingest_cache_enabled:
            ingest_cache.save(raw_filename, content, {
                "pages_created": pages_created,
                "pages_updated": pages_updated,
            })
            logger.info(f"[Ingest] Cache saved for {raw_filename}")

    result.tokens_used = {"input": total_input_tokens, "output": total_output_tokens}
    logger.info(f"[Ingest] All sources done: {len(result.pages_created)} created, {len(result.pages_updated)} updated, tokens={result.tokens_used}")
    return result


async def _ingest_one(
    filename: str, content: str, task: Task
) -> tuple[list[str], list[str], int, dict]:
    """处理单个 source 文件的完整 Ingest"""
    pages_created = []
    pages_updated = []
    pages_merged = 0
    total_tokens = {"input": 0, "output": 0}

    # 读取上下文
    purpose = wiki_manager.read_purpose()
    schema = wiki_manager.read_schema()
    index = wiki_manager.read_index()
    overview = wiki_manager.read_overview()

    # Step 1: 分析
    task.update_progress(f"Analyzing {filename}")
    logger.info(f"[Ingest] Step 1: Analyzing {filename}")
    analysis_messages = build_analysis_prompt(
        purpose=purpose,
        index=index,
        source_content=content,
        target_lang=settings.output_language,
    )
    analysis_result, usage1 = await llm_client.achat(analysis_messages)
    total_tokens["input"] += usage1.get("input", 0)
    total_tokens["output"] += usage1.get("output", 0)
    logger.info(f"[Ingest] Step 1 done: analysis tokens={usage1}")

    # Step 2: 生成
    task.update_progress(f"Generating wiki pages for {filename}")
    logger.info(f"[Ingest] Step 2: Generating wiki pages for {filename}")
    generation_messages = build_generation_prompt(
        schema=schema,
        purpose=purpose,
        index=index,
        source_file_name=filename,
        analysis_result=analysis_result,
        overview=overview,
        source_content=content,
        target_lang=settings.output_language,
    )
    generation_result, usage2 = await llm_client.achat(generation_messages, max_tokens=32000)
    total_tokens["input"] += usage2.get("input", 0)
    total_tokens["output"] += usage2.get("output", 0)
    logger.info(f"[Ingest] Step 2 done: generation tokens={usage2}, response length={len(generation_result)}")

    # Step 3: 解析文件块
    parse_result = parse_file_blocks(generation_result)
    logger.info(f"[Ingest] Step 3: Parsed {len(parse_result.blocks)} file blocks, {len(parse_result.warnings)} warnings")

    # Step 4: 写入文件块
    hard_failures = []
    logger.info(f"[Ingest] Step 4: Writing {len(parse_result.blocks)} file blocks")
    for block in parse_result.blocks:
        path = block.path

        # 路径安全检查
        if not is_safe_ingest_path(path):
            hard_failures.append(f"Unsafe path: {path}")
            logger.warning(f"[Ingest] Skipping unsafe path: {path}")
            continue

        rel_path = sanitize_path(path)

        # 清洗 LLM 输出（剥离代码围栏、frontmatter: 前缀、修复 wikilink 列表）
        content = sanitize_ingested_content(block.content)

        # 语言守卫
        if not content_matches_target_language(content, settings.output_language):
            logger.warning(f"[Ingest] Language mismatch for {path}, skipping")
            continue

        # 写入策略
        if rel_path == "log.md":
            # 追加
            wiki_manager.append_to_file("log.md", content + "\n")
            pages_updated.append("log.md")
            logger.info(f"[Ingest] Appended to log.md")
        elif rel_path in ("index.md", "overview.md"):
            # 对齐官方：listing pages 直接覆盖（LLM 生成时已参考现有 index/overview）
            wiki_manager.write_wiki_page(rel_path, content)
            pages_updated.append(rel_path)
            logger.info(f"[Ingest] Overwrote {rel_path}")
        else:
            # 合并
            existing = wiki_manager.read_wiki_page(rel_path)

            async def merger_fn(existing_content, new_content, source_name):
                messages = build_page_merger_prompt(
                    existing_content, new_content, source_name, settings.output_language
                )
                text, _ = await llm_client.achat(messages)
                return text

            def backup_fn(existing_content):
                backup_page(settings.wiki_root, rel_path, existing_content)

            merged, was_llm = await merge_page_content(
                new_content=content,
                existing_content=existing,
                merger_fn=merger_fn,
                source_file_name=filename,
                backup_fn=backup_fn,
                target_lang=settings.output_language,
            )
            wiki_manager.write_wiki_page(rel_path, merged)
            if existing is None:
                pages_created.append(rel_path)
                logger.info(f"[Ingest] Created new page: {rel_path}")
            else:
                pages_updated.append(rel_path)
                if was_llm:
                    pages_merged += 1
                    logger.info(f"[Ingest] Merged (LLM) existing page: {rel_path}")
                else:
                    logger.info(f"[Ingest] Updated existing page: {rel_path}")

    # Step 5: 解析 Review 块（暂存，后续通过 /api/reviews 查看）
    reviews = parse_review_blocks(generation_result)

    return pages_created, pages_updated, pages_merged, total_tokens


def _find_raw_file(source_id: str) -> Optional[str]:
    """查找 raw 文件名"""
    raw_sources = wiki_manager.list_raw_sources()
    # 精确匹配
    if source_id in raw_sources:
        return source_id
    # 模糊匹配
    for f in raw_sources:
        stem = os.path.splitext(f)[0]
        if stem == source_id or source_id in f:
            return f
    return None


def get_uningested_sources() -> list[str]:
    """获取所有未 Ingest 的 raw 源文件"""
    raw_sources = wiki_manager.list_raw_sources()
    uningested = []
    for f in raw_sources:
        # 检查 wiki/sources/ 下是否有对应摘要
        stem = os.path.splitext(f)[0]
        summary_path = os.path.join("sources", f"{stem}.md")
        if not wiki_manager.read_wiki_page(summary_path):
            uningested.append(stem)
    return uningested
