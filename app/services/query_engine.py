"""Query 检索管线，对齐桌面版 Query 流程

token搜索 → vector搜索(可选) → RRF融合 → LLM综合回答 → 可选写回wiki
"""

import logging
from datetime import date
from typing import Optional

from app.config import settings
from app.models.wiki import QueryResponse, Citation
from app.prompts.language import language_rule
from app.safety.project_lock import ProjectLock
from app.services.llm_client import llm_client
from app.services.search import SearchService, tokenize_query
from app.services.wiki_manager import wiki_manager

logger = logging.getLogger(__name__)


async def run_query(
    question: str,
    save_to_wiki: bool = True,
    language: str = "",
) -> QueryResponse:
    """执行智能问答"""
    target_lang = language or settings.output_language
    logger.info(f"[Query] Received question: {question!r} (lang={target_lang}, save={save_to_wiki})")

    # Step 1: 检索相关页面
    search_svc = SearchService(wiki_manager)
    results, total = search_svc.search(keyword=question, limit=10)
    logger.info(f"[Query] Search returned {total} results, top {len(results)} taken")

    if not results:
        # 无相关页面，直接让 LLM 回答
        logger.info(f"[Query] No relevant pages found, falling back to direct answer")
        return await _direct_answer(question, target_lang, save_to_wiki)

    # Step 2: 读取相关页面内容
    page_contents = []
    citations = []
    for r in results[:5]:  # 取 Top-5
        content = wiki_manager.read_wiki_page(f"{r['slug']}.md")
        if content:
            page_contents.append(f"## {r['title']}\n{content}")
            citations.append(Citation(
                slug=r["slug"],
                title=r["title"],
                relevance="直接相关",
            ))
    logger.info(f"[Query] Read {len(page_contents)} pages for context: {[c.slug for c in citations]}")

    # Step 3: 组装上下文 + LLM 回答
    purpose = wiki_manager.read_purpose()
    schema_content = wiki_manager.read_schema()
    lang_rule = language_rule(None, target_lang)

    context = "\n\n---\n\n".join(page_contents)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a knowledgeable assistant with access to a structured wiki. "
                "Answer the user's question based on the wiki content provided. "
                "Cite specific pages when making claims. "
                "If the wiki content is insufficient, say so honestly."
                + lang_rule
            ),
        },
        {
            "role": "user",
            "content": (
                f"## Wiki Purpose\n{purpose}\n\n"
                f"## Relevant Wiki Pages\n{context}\n\n"
                f"## Question\n{question}\n\n"
                "Answer based on the wiki content above. Cite pages using [[page-slug]] syntax."
                + lang_rule
            ),
        },
    ]

    answer, usage = await llm_client.achat(messages, max_tokens=8000)
    logger.info(f"[Query] LLM answered: tokens={usage}, answer length={len(answer)}")

    # Step 4: 可选写回 wiki
    wiki_page_created = ""
    if save_to_wiki and len(answer) > 200:
        wiki_page_created = await _save_answer_to_wiki(
            question, answer, citations, target_lang
        )
        logger.info(f"[Query] Answer saved to wiki: {wiki_page_created}")

    return QueryResponse(
        answer=answer,
        citations=citations,
        wiki_page_created=wiki_page_created,
        tokens_used=usage,
    )


async def _direct_answer(
    question: str, target_lang: str, save_to_wiki: bool
) -> QueryResponse:
    """无相关页面时直接回答"""
    lang_rule = language_rule(None, target_lang)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. The wiki does not contain relevant "
                "information for this question. Answer based on general knowledge."
                + lang_rule
            ),
        },
        {"role": "user", "content": question + lang_rule},
    ]
    answer, usage = await llm_client.achat(messages, max_tokens=4000)
    return QueryResponse(answer=answer, tokens_used=usage)


async def _save_answer_to_wiki(
    question: str, answer: str, citations: list[Citation], target_lang: str
) -> str:
    """将优质答案写回 wiki（项目锁保护）"""
    from app.services.page_merger import backup_page

    # 生成 slug
    import re
    slug = re.sub(r'[^\w\u4e00-\u9fff-]', '-', question[:30]).strip('-').lower()
    slug = re.sub(r'-+', '-', slug)
    rel_path = f"queries/{slug}.md"

    # 构建 frontmatter
    related = [c.slug for c in citations]
    today = date.today().isoformat()
    page_content = (
        f"---\n"
        f"type: query\n"
        f"title: \"{question[:50]}\"\n"
        f"tags: []\n"
        f"related: [{', '.join(related)}]\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"sources: []\n"
        f"---\n"
        f"# {question}\n\n{answer}\n"
    )

    with ProjectLock():
        # 检查是否已存在
        existing = wiki_manager.read_wiki_page(rel_path)
        if existing:
            backup_page(settings.wiki_root, rel_path, existing)
        wiki_manager.write_wiki_page(rel_path, page_content)

    return rel_path
