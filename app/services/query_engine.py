"""Query 检索管线，对齐桌面版 chat-panel.tsx handleSend 流程

token搜索 → graph 1跳扩展 → 预算控制 → 优先级填充 → 编号引用 → LLM 综合回答
"""

import logging
import math
import re
from datetime import date
from typing import Optional

from app.config import settings
from app.models.wiki import QueryResponse, Citation
from app.prompts.language import language_rule, LANG_MAP
from app.safety.project_lock import ProjectLock
from app.services.context_budget import compute_context_budget
from app.services.graph_relevance import build_retrieval_graph, get_related_nodes
from app.services.llm_client import llm_client
from app.services.search import SearchService, tokenize_query
from app.services.wiki_manager import wiki_manager

logger = logging.getLogger(__name__)


# --- 问候检测（对齐官方 greeting-detector.ts） ---
_GREETING_PATTERNS = re.compile(
    r"^(hi|hello|hey|你好|嗨|哈喽|您好|早上好|下午好|晚上好|good morning|good afternoon|good evening)[\s!！。.？?]*$",
    re.IGNORECASE,
)


def _is_greeting(text: str) -> bool:
    stripped = text.strip()
    return bool(_GREETING_PATTERNS.match(stripped)) and len(stripped) <= 20


def _parse_frontmatter_sources(content: str) -> list[str]:
    """从 frontmatter 解析 sources 数组（支持 block form 和 inline form）"""
    fm_match = re.match(r"^---\n([\s\S]*?)\n---", content)
    if not fm_match:
        return []
    fm = fm_match.group(1)

    # block form: sources:\n  - a\n  - b
    block_match = re.match(r"^sources:\s*\n((?:\s+-\s+.+\n?)*)", fm, re.MULTILINE)
    if block_match:
        sources = []
        for line in block_match.group(1).split("\n"):
            item_match = re.match(r"^\s+-\s+[\"']?(.+?)[\"']?\s*$", line)
            if item_match:
                sources.append(item_match.group(1))
        return sources

    # inline form: sources: [a, b]
    inline_match = re.match(r"^sources:\s*\[([^\]]*)\]", fm, re.MULTILINE)
    if inline_match:
        items = inline_match.group(1).split(",")
        return [i.strip().strip("\"'") for i in items if i.strip()]

    return []


async def run_query(
    question: str,
    save_to_wiki: bool = True,
    language: str = "",
) -> QueryResponse:
    """执行智能问答，对齐官方 chat-panel.tsx handleSend 流程"""
    target_lang = language or settings.output_language
    logger.info(f"[Query] Received question: {question!r} (lang={target_lang}, save={save_to_wiki})")

    # 问候检测 — 跳过检索，直接对话
    if _is_greeting(question):
        logger.info("[Query] Greeting detected, skipping retrieval")
        return await _direct_answer(question, target_lang)

    # ── Phase 1: 预算分配 ──
    budget = compute_context_budget(settings.llm_max_context)
    logger.info(
        f"[Query] Budget: maxCtx={budget.max_ctx}, "
        f"indexBudget={budget.index_budget}, pageBudget={budget.page_budget}, "
        f"maxPageSize={budget.max_page_size}"
    )

    # ── Phase 2: Token + 向量搜索 → RRF 融合 → Top 10 ──
    search_svc = SearchService(wiki_manager)
    search_results, total = await search_svc.search_with_rrf(keyword=question, limit=10)
    top_search = search_results[:10]
    logger.info(f"[Query] Search (RRF) returned {total} results, top {len(top_search)} taken")

    if not top_search:
        logger.info("[Query] No search results, falling back to direct answer")
        return await _direct_answer(question, target_lang, save_to_wiki)

    # ── Phase 3: Wiki Index 注入（裁剪至预算） ──
    raw_index = wiki_manager.read_index()
    index_content = _trim_index(raw_index, question, budget.index_budget)

    # ── Phase 4: Graph 1 跳扩展 ──
    graph = build_retrieval_graph(wiki_manager)
    # 对齐桌面版：图中 node_id 是文件名（不含目录前缀），搜索结果的 slug 含目录前缀
    # 需要从 slug 提取 filename 来匹配图节点
    import os as _os
    # 对齐桌面版：searchHitPaths 用 node.path（完整相对路径如 entities/takin-platform.md）
    # 用于 graph expansion 去重，避免搜索命中页被重复添加
    search_hit_paths = {r["slug"] + ".md" for r in top_search}
    expanded_ids: set[str] = set()
    graph_expansions: list[dict] = []

    for r in top_search:
        # slug → filename-based node_id（对齐桌面版 fileNameToId）
        node_id = _os.path.basename(r["slug"])
        related = get_related_nodes(node_id, graph, limit=3)
        for node, relevance in related:
            if relevance < 2.0:
                continue
            # 对齐桌面版：用 node.path 判重（searchHitPaths.has(node.path)）
            if node.path in search_hit_paths:
                continue
            if node.id in expanded_ids:
                continue
            expanded_ids.add(node.id)
            graph_expansions.append({
                "title": node.title,
                "path": node.path,
                "slug": node.id,
                "relevance": relevance,
            })

    graph_expansions.sort(key=lambda x: -x["relevance"])
    logger.info(
        f"[Query] Graph expansion: {len(graph_expansions)} nodes, "
        f"slugs={[g['slug'] for g in graph_expansions]}"
    )

    # ── Phase 5: 优先级填充页面（P0→P1→P2→P3） ──
    used_chars = 0
    relevant_pages: list[dict] = []

    def try_add_page(title: str, rel_path: str, slug: str, priority: int) -> bool:
        nonlocal used_chars
        if used_chars >= budget.page_budget:
            return False
        content = wiki_manager.read_wiki_page(rel_path)
        if content is None:
            return False
        if len(content) > budget.max_page_size:
            content = content[:budget.max_page_size] + "\n\n[...truncated...]"
        if used_chars + len(content) > budget.page_budget:
            return False
        used_chars += len(content)
        relevant_pages.append({
            "title": title,
            "path": rel_path,
            "slug": slug,
            "content": content,
            "priority": priority,
        })
        return True

    # P0: 标题匹配的搜索结果
    for r in top_search:
        if r.get("title_match", False):
            try_add_page(r["title"], r["slug"] + ".md", r["slug"], 0)

    # P1: 内容匹配的搜索结果（标题不匹配）
    for r in top_search:
        if not r.get("title_match", False):
            try_add_page(r["title"], r["slug"] + ".md", r["slug"], 1)

    # P2: 图谱扩展节点
    for exp in graph_expansions:
        try_add_page(exp["title"], exp["path"], exp["slug"], 2)

    # P3: Overview 兜底
    if not relevant_pages:
        try_add_page("Overview", "overview.md", "overview", 3)

    logger.info(
        f"[Query] Loaded {len(relevant_pages)} pages, used {used_chars}/{budget.page_budget} chars, "
        f"slugs={[p['slug'] for p in relevant_pages]}"
    )

    # ── Phase 6: 组装编号上下文 + System Prompt ──
    pages_context = "\n\n---\n\n".join(
        f"### [{i + 1}] {p['title']}\nPath: {p['path']}\n\n{p['content']}"
        for i, p in enumerate(relevant_pages)
    ) if relevant_pages else "(No wiki pages found)"

    page_list = "\n".join(
        f"[{i + 1}] {p['title']} ({p['path']})"
        for i, p in enumerate(relevant_pages)
    )

    purpose = wiki_manager.read_purpose()
    lang_name = LANG_MAP.get(target_lang.lower(), target_lang)

    system_content = "\n".join(filter(None, [
        "You are a knowledgeable wiki assistant. Answer questions based on the wiki content provided below.",
        "",
        "## Rules",
        "- Answer based ONLY on the numbered wiki pages provided below.",
        "- If the provided pages don't contain enough information, say so honestly.",
        "- Use [[wikilink]] syntax to reference wiki pages.",
        "- When citing information, use the page number in brackets, e.g. [1], [2].",
        "- Cite ALL pages that contribute to your answer — do not omit relevant pages.",
        "- Provide a THOROUGH and COMPREHENSIVE answer that leverages the full breadth of relevant wiki pages.",
        "- At the VERY END of your response, add a hidden comment listing which page numbers you used:",
        "  <!-- cited: 1, 3, 5 -->",
        "",
        "Use markdown formatting for clarity.",
        "",
        f"## Wiki Purpose\n{purpose}" if purpose else "",
        f"## Wiki Index\n{index_content}" if index_content else "",
        f"## Page List\n{page_list}" if relevant_pages else "",
        f"## Wiki Pages\n\n{pages_context}",
        "",
        "---",
        "",
        f"## ⚠️ MANDATORY OUTPUT LANGUAGE: {lang_name}",
        "",
        f"You MUST write your entire response in **{lang_name}**.",
        f"The wiki content above may be in a different language, but this is IRRELEVANT to your output language.",
        f"Ignore the language of the wiki content. Write in {lang_name} only.",
        f"Even proper nouns should use standard {lang_name} transliteration when appropriate.",
        f"DO NOT use any other language. This overrides all other instructions.",
    ]))

    # 对齐桌面版：langReminder 注入到用户消息前（强化输出语言约束）
    lang_reminder = f"REMINDER: All output must be in {lang_name}. Do not use any other language."
    user_content = f"[{lang_reminder}]\n\n{question}"

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

    # ── Phase 7: LLM 调用 ──
    # 对齐桌面版：不硬编码 max_tokens，由 response_reserve 自然限制输出长度
    # 桌面版不传 max_tokens，模型可利用全部剩余上下文空间生成完整回答
    answer, usage = await llm_client.achat(messages)
    logger.info(f"[Query] LLM answered: tokens={usage}, answer length={len(answer)}")

    # ── Phase 8: 解析引用编号 ──
    citations = _extract_citations(answer, relevant_pages)

    # ── Phase 9: 可选写回 wiki ──
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


def _trim_index(raw_index: str, query: str, budget: int) -> str:
    """裁剪 index.md 到预算内（对齐官方 chat-panel index trimming）"""
    if not raw_index or len(raw_index) <= budget:
        return raw_index

    tokens = tokenize_query(query)
    lines = raw_index.split("\n")
    kept_lines: list[str] = []
    kept_size = 0

    for line in lines:
        is_header = line.startswith("##")
        lower = line.lower()
        is_relevant = any(t.lower() in lower for t in tokens)

        if is_header or is_relevant:
            if kept_size + len(line) + 1 <= budget:
                kept_lines.append(line)
                kept_size += len(line) + 1

    result = "\n".join(kept_lines)
    if len(result) < len(raw_index):
        result += "\n\n[...index trimmed to relevant entries...]"
    return result


def _extract_citations(
    answer: str, relevant_pages: list[dict]
) -> list[Citation]:
    """从回答中提取引用（对齐官方 extractCitedPages 三级回退）

    1. 优先解析 <!-- cited: 1, 3, 5 --> 隐藏注释
    2. 回退：解析正文中的 [1], [2]
    3. 最终回退：解析 [[wikilinks]]
    """
    citations: list[Citation] = []
    cited_indices: set[int] = set()

    # 1. 优先解析 <!-- cited: ... -->
    cited_match = re.search(r"<!--\s*cited:\s*([\d,\s]+)\s*-->", answer)
    if cited_match:
        for num_str in cited_match.group(1).split(","):
            num_str = num_str.strip()
            if num_str.isdigit():
                cited_indices.add(int(num_str))

    # 2. 回退：正文 [1], [2]
    if not cited_indices:
        for m in re.finditer(r"\[(\d+)\]", answer):
            cited_indices.add(int(m.group(1)))

    # 映射到页面
    for idx in sorted(cited_indices):
        if 1 <= idx <= len(relevant_pages):
            page = relevant_pages[idx - 1]
            citations.append(Citation(
                slug=page["slug"],
                title=page["title"],
                relevance=f"[{idx}]",
            ))

    # 3. 最终回退：[[wikilinks]]
    if not citations:
        for m in re.finditer(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]", answer):
            slug = m.group(1).strip()
            for page in relevant_pages:
                if page["slug"] == slug or page["slug"].endswith(slug):
                    if not any(c.slug == page["slug"] for c in citations):
                        citations.append(Citation(
                            slug=page["slug"],
                            title=page["title"],
                            relevance="直接相关",
                        ))

    return citations


async def _direct_answer(
    question: str, target_lang: str, save_to_wiki: bool = False
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
    answer, usage = await llm_client.achat(messages)
    return QueryResponse(answer=answer, tokens_used=usage)


async def _save_answer_to_wiki(
    question: str, answer: str, citations: list[Citation], target_lang: str
) -> str:
    """将优质答案写回 wiki（项目锁保护）"""
    from app.services.page_merger import backup_page

    # 生成 slug
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
