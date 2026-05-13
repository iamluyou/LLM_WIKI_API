"""混合检索服务，对齐桌面版 search.ts

Token 词法搜索 + 向量搜索（可选）+ RRF 融合
"""

import os
import re
import logging
from typing import Optional

from app.config import settings
from app.services.wiki_manager import WikiManager

logger = logging.getLogger(__name__)

# --- 评分权重（对齐桌面版 scoreFile） ---
FILENAME_EXACT_BONUS = 200
PHRASE_IN_TITLE_BONUS = 50
PHRASE_IN_CONTENT_PER_OCC = 20
PHRASE_IN_CONTENT_MAX_OCC = 10
TITLE_TOKEN_WEIGHT = 5
CONTENT_TOKEN_WEIGHT = 1

# --- RRF 融合参数 ---
RRF_K = 60

# --- 停用词（对齐桌面版 STOP_WORDS，30个） ---
STOP_WORDS = {
    "的", "是", "了", "什么", "在", "有", "和", "与", "对", "从",
    "the", "is", "a", "an", "what", "how", "are", "was", "were",
    "do", "does", "did", "be", "been", "being", "have", "has", "had",
    "it", "its", "in", "on", "at", "to", "for", "of", "with", "by",
    "this", "that", "these", "those",
}


def tokenize_query(query: str) -> list[str]:
    """CJK bigram + 英文分词 + 停用词过滤，对齐桌面版 tokenizeQuery"""
    # 对齐桌面版：先转小写再分词
    query_lower = query.lower()
    # 基础分割（对齐桌面版正则，不含多余英文标点）
    parts = re.split(r'[\s,，。！？、；：""''（）()\-_/\\·~～…]+', query_lower)
    raw_tokens = [p for p in parts if len(p) > 1 and p not in STOP_WORDS]

    tokens: list[str] = []

    for token in raw_tokens:
        # CJK 检测
        has_cjk = bool(re.search(r'[\u4e00-\u9fff\u3400-\u4dbf]', token))

        if has_cjk and len(token) > 2:
            # 对齐桌面版：CJK bigram（不做额外 cjk_chars>2 限制）
            chars = list(token)
            for i in range(len(chars) - 1):
                tokens.append(chars[i] + chars[i + 1])
            # 单字（对齐桌面版：过滤停用词）
            for ch in chars:
                if ch not in STOP_WORDS:
                    tokens.append(ch)
            # 保留原始 token
            tokens.append(token)
        else:
            tokens.append(token)

    # 对齐桌面版：去重（桌面版 [...new Set(tokens)]，因已 lowercase 等价）
    seen = set()
    result = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _extract_title(content: str, filename: str) -> str:
    """从内容提取标题：frontmatter title > # heading > 文件名"""
    # frontmatter title
    fm_match = re.match(r'^---\n[\s\S]*?title:\s*["\']?(.+?)["\']?\s*\n[\s\S]*?\n---', content)
    if fm_match:
        return fm_match.group(1).strip()

    # # heading
    heading_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if heading_match:
        return heading_match.group(1).strip()

    # 文件名
    return os.path.splitext(filename)[0].replace("-", " ")


def score_file(content: str, filename: str, tokens: list[str], query_phrase: str) -> tuple[Optional[float], bool]:
    """评分函数，对齐桌面版 scoreFile
    
    Returns:
        (score, title_match): score 为 None 表示不匹配，title_match 表示标题中包含查询短语
    """
    title = _extract_title(content, filename)
    stem = os.path.splitext(filename)[0]
    content_lower = content.lower()
    # 对齐桌面版：titleText = title + " " + filename
    title_text = f"{title} {filename}"
    title_lower = title_text.lower()
    stem_lower = stem.lower()

    # 对齐桌面版：清理 query phrase 首尾标点（与桌面版 TRIM_PUNCT_RE 一致，不含英文 .!?;:）
    _TRIM_PUNCT_RE = r'^[\s,，。！？、；：""''（）()\-_/\\·~～…]+|[\s,，。！？、；：""''（）()\-_/\\·~～…]+$'
    cleaned_phrase = re.sub(_TRIM_PUNCT_RE, '', query_phrase.strip().lower())

    score = 0.0
    title_match = False

    # FILENAME_EXACT_BONUS — 对齐桌面版：filenameExact 不单独设 titleMatch
    if stem_lower == cleaned_phrase:
        score += FILENAME_EXACT_BONUS

    # PHRASE_IN_TITLE_BONUS
    if cleaned_phrase and cleaned_phrase in title_lower:
        score += PHRASE_IN_TITLE_BONUS
        title_match = True

    # PHRASE_IN_CONTENT_PER_OCC
    if cleaned_phrase:
        occ = content_lower.count(cleaned_phrase)
        score += min(occ, PHRASE_IN_CONTENT_MAX_OCC) * PHRASE_IN_CONTENT_PER_OCC

    # TITLE_TOKEN_WEIGHT — 对齐桌面版 tokenMatchScore: 二值匹配（出现=1，不出现=0）
    for token in tokens:
        if token.lower() in title_lower:
            score += TITLE_TOKEN_WEIGHT
            title_match = True

    # CONTENT_TOKEN_WEIGHT — 对齐桌面版 tokenMatchScore: 二值匹配
    for token in tokens:
        if token.lower() in content_lower:
            score += CONTENT_TOKEN_WEIGHT

    return (score, title_match) if score > 0 else (None, False)


def build_snippet(content: str, query: str, context_chars: int = 80) -> str:
    """构建搜索结果摘要，对齐桌面版 buildSnippet"""
    lower = content.lower()
    lower_query = query.lower()
    idx = lower.find(lower_query)
    if idx == -1:
        # 对齐桌面版：无匹配时返回开头，不加尾部 "..."
        return content[:context_chars * 2].replace("\n", " ")

    start = max(0, idx - context_chars)
    end = min(len(content), idx + len(query) + context_chars)
    snippet = content[start:end].replace("\n", " ")
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    return snippet


class SearchService:
    def __init__(self, wiki_manager: WikiManager):
        self.wm = wiki_manager

    def _token_search(
        self,
        keyword: str = "",
        page_type: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list[dict]:
        """纯 token 搜索，返回带 score 的完整结果"""
        wiki_files = self.wm.list_wiki_files()
        results = []

        tokens = tokenize_query(keyword) if keyword else []
        # 对齐桌面版：effectiveTokens fallback — 全部过滤后用原始 query
        effective_tokens = tokens if tokens else [keyword.strip().lower()] if keyword else []
        query_phrase = keyword

        for rel_path in wiki_files:
            filename = os.path.basename(rel_path)

            content = self.wm.read_wiki_page(rel_path)
            if content is None:
                continue

            fm = self.wm.parse_frontmatter(content)

            # 类型过滤
            if page_type:
                if fm.get("type", "") != page_type:
                    continue

            # 标签过滤
            if tag:
                if tag not in fm.get("tags", []):
                    continue

            # 评分
            title_match = False
            if keyword:
                s, title_match = score_file(content, filename, effective_tokens, query_phrase)
                if s is None:
                    continue
            else:
                s = 0.0

            slug = os.path.splitext(rel_path)[0]
            # 对齐桌面版：snippet 锚点选择 phrase > token > query
            content_lower = content.lower()
            cleaned_phrase = re.sub(
                r'^[\s,，。！？、；：""''（）()\-_/\\·~～…]+|[\s,，。！？、；：""''（）()\-_/\\·~～…]+$',
                '', query_phrase.strip().lower()
            ) if keyword else ""
            phrase_occ = content_lower.count(cleaned_phrase) if cleaned_phrase else 0
            if phrase_occ > 0:
                snippet_anchor = cleaned_phrase
            else:
                # 找第一个在内容中出现的 token
                snippet_anchor = next(
                    (t for t in effective_tokens if t.lower() in content_lower),
                    keyword
                )

            results.append({
                "slug": slug,
                "type": fm.get("type", ""),
                "title": fm.get("title", _extract_title(content, filename)),
                "tags": fm.get("tags", []),
                "related": fm.get("related", []),
                "created": str(fm.get("created", "")),
                "updated": str(fm.get("updated", "")),
                "content": content,
                "snippet": build_snippet(content, snippet_anchor) if keyword else "",
                "score": s,
                "title_match": title_match,
            })

        # 按 token 分数降序排序
        results.sort(key=lambda x: (-x["score"], x["slug"]))
        return results

    async def search_with_rrf(
        self,
        keyword: str = "",
        page_type: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """混合搜索：Token + 向量(可选) + RRF 融合，对齐官方 searchWiki"""
        # ── Phase 1: Token 搜索 ──
        token_results = self._token_search(keyword, page_type, tag)

        # 快照 token 排名（在向量搜索添加结果前）
        token_rank: dict[str, int] = {}
        for i, r in enumerate(token_results):
            token_rank[r["slug"]] = i + 1  # 1-indexed

        # ── Phase 2: 向量搜索（可选） ──
        vector_rank: dict[str, int] = {}
        vector_results: list[dict] = []

        if settings.embedding_enabled and settings.embedding_model and keyword:
            try:
                from app.services.embedding import search_by_embedding
                vec_results = await search_by_embedding(self.wm.wiki_root, keyword, 10)
                for i, vr in enumerate(vec_results):
                    page_id = vr["id"]
                    vector_rank[page_id] = i + 1  # 1-indexed

                    # 如果 token 搜索已有此页面，跳过（后面融合时用排名）
                    if page_id in token_rank:
                        continue

                    # 向量搜索独有的页面：需要 materialize（读取内容）
                    content = self._find_page_content(page_id)
                    if content is None:
                        continue

                    fm = self.wm.parse_frontmatter(content)
                    filename = page_id.split("/")[-1] + ".md" if "/" in page_id else page_id + ".md"
                    slug = page_id

                    vector_results.append({
                        "slug": slug,
                        "type": fm.get("type", ""),
                        "title": fm.get("title", _extract_title(content, filename)),
                        "tags": fm.get("tags", []),
                        "related": fm.get("related", []),
                        "created": str(fm.get("created", "")),
                        "updated": str(fm.get("updated", "")),
                        "content": content,
                        "snippet": build_snippet(content, keyword),
                        "score": 0.0,  # 会被 RRF 覆盖
                        "title_match": False,
                    })

                logger.info(
                    f"[Search] Vector: {len(vec_results)} results, "
                    f"{len(vector_results)} new pages materialized"
                )
            except Exception as e:
                logger.warning(f"[Search] Vector search skipped: {e}")
                vector_rank = {}

        # ── 合并结果集 ──
        all_results = token_results + vector_results

        # ── Phase 3: RRF 融合 ──
        for r in all_results:
            t_rank = token_rank.get(r["slug"])
            v_rank = vector_rank.get(r["slug"])
            rrf = 0.0
            if t_rank is not None:
                rrf += 1.0 / (RRF_K + t_rank)
            if v_rank is not None:
                rrf += 1.0 / (RRF_K + v_rank)
            r["score"] = rrf

        # 按 RRF 分数排序（同分按路径字典序）
        all_results.sort(key=lambda x: (-x["score"], x["slug"]))

        total = len(all_results)
        paged = all_results[offset: offset + limit]

        # 移除内部字段（保留 title_match 给 query_engine 用）
        for r in paged:
            r.pop("score", None)

        logger.info(
            f"[Search] RRF fused: {len(token_rank)} token + "
            f"{len(vector_rank)} vector → {total} unique"
        )

        return paged, total

    def search(
        self,
        keyword: str = "",
        page_type: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """同步搜索接口（向后兼容，不含向量搜索）"""
        results = self._token_search(keyword, page_type, tag)
        total = len(results)
        paged = results[offset: offset + limit]

        # 移除内部字段（保留 title_match 给 query_engine 用）
        for r in paged:
            r.pop("score", None)

        return paged, total

    def _find_page_content(self, page_id: str) -> Optional[str]:
        """根据 page_id 查找页面内容（尝试多个目录）"""
        dirs = ["entities", "concepts", "sources", "synthesis", "comparison", "queries"]
        for d in dirs:
            rel_path = f"{d}/{page_id}.md" if "/" not in page_id else f"{page_id}.md"
            content = self.wm.read_wiki_page(rel_path)
            if content is not None:
                return content
        # 如果 page_id 本身含路径前缀
        content = self.wm.read_wiki_page(page_id + ".md")
        return content
