"""混合检索服务，对齐桌面版 search.ts

Token 词法搜索 + 向量搜索（可选）+ RRF 融合
"""

import os
import re
from typing import Optional

from app.services.wiki_manager import WikiManager

# --- 评分权重（对齐桌面版 scoreFile） ---
FILENAME_EXACT_BONUS = 200
PHRASE_IN_TITLE_BONUS = 50
PHRASE_IN_CONTENT_PER_OCC = 20
PHRASE_IN_CONTENT_MAX_OCC = 10
TITLE_TOKEN_WEIGHT = 5
CONTENT_TOKEN_WEIGHT = 1

# --- RRF 融合参数 ---
RRF_K = 60

# --- 停用词 ---
CN_STOPWORDS = {"的", "是", "了", "什么", "在", "有", "和", "与", "对", "从", "为", "被", "把", "让", "也", "都", "而", "及", "其", "这", "那", "我", "你", "他", "她", "它", "们"}
EN_STOPWORDS = {"the", "is", "a", "an", "what", "how", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "shall", "can", "to", "of", "in", "for", "on", "with", "at", "by", "from", "as", "into", "through", "during", "before", "after", "above", "below", "between", "and", "or", "but", "not", "no", "nor"}


def tokenize_query(query: str) -> list[str]:
    """CJK bigram + 英文分词 + 停用词过滤，对齐桌面版 tokenizeQuery"""
    # 基础分割
    parts = re.split(r'[\s，。！？、；：""''（）\-_/·~～…,.\-!?;:()]+', query)
    tokens = []
    for part in parts:
        part = part.strip()
        if len(part) <= 1:
            continue
        # CJK 检测
        cjk_chars = re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', part)
        if len(cjk_chars) > 2 and len(part) > 2:
            # 生成 bigram
            for i in range(len(part) - 1):
                bigram = part[i:i + 2]
                if any('\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf' for c in bigram):
                    tokens.append(bigram)
            # 单字
            for c in part:
                if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf':
                    tokens.append(c)
            # 原始 token
            tokens.append(part)
        else:
            tokens.append(part)

    # 停用词过滤 + 去重
    filtered = []
    seen = set()
    for t in tokens:
        t_lower = t.lower()
        if t_lower in CN_STOPWORDS or t_lower in EN_STOPWORDS:
            continue
        if t_lower not in seen:
            seen.add(t_lower)
            filtered.append(t)
    return filtered


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


def score_file(content: str, filename: str, tokens: list[str], query_phrase: str) -> Optional[float]:
    """评分函数，对齐桌面版 scoreFile"""
    title = _extract_title(content, filename)
    stem = os.path.splitext(filename)[0]
    content_lower = content.lower()
    title_lower = title.lower()
    stem_lower = stem.lower()

    score = 0.0

    # FILENAME_EXACT_BONUS
    if stem_lower == query_phrase.lower():
        score += FILENAME_EXACT_BONUS

    # PHRASE_IN_TITLE_BONUS
    if query_phrase.lower() in title_lower:
        score += PHRASE_IN_TITLE_BONUS

    # PHRASE_IN_CONTENT_PER_OCC
    if query_phrase:
        occ = content_lower.count(query_phrase.lower())
        score += min(occ, PHRASE_IN_CONTENT_MAX_OCC) * PHRASE_IN_CONTENT_PER_OCC

    # TITLE_TOKEN_WEIGHT
    for token in tokens:
        if token.lower() in title_lower:
            score += TITLE_TOKEN_WEIGHT

    # CONTENT_TOKEN_WEIGHT
    for token in tokens:
        score += content_lower.count(token.lower()) * CONTENT_TOKEN_WEIGHT

    return score if score > 0 else None


def build_snippet(content: str, query: str, context_chars: int = 80) -> str:
    """构建搜索结果摘要，对齐桌面版 buildSnippet"""
    idx = content.lower().find(query.lower())
    if idx == -1:
        return content[:context_chars * 2] + "..." if len(content) > context_chars * 2 else content

    start = max(0, idx - context_chars)
    end = min(len(content), idx + len(query) + context_chars)
    snippet = content[start:end].replace("\n", " ")
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    return f"{prefix}{snippet}{suffix}"


class SearchService:
    def __init__(self, wiki_manager: WikiManager):
        self.wm = wiki_manager

    def search(
        self,
        keyword: str = "",
        page_type: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """搜索 wiki 页面，返回 (结果列表, 总数)"""
        wiki_files = self.wm.list_wiki_files()
        results = []

        # Token 搜索
        tokens = tokenize_query(keyword) if keyword else []
        query_phrase = keyword

        for rel_path in wiki_files:
            filename = os.path.basename(rel_path)

            # 类型过滤
            if page_type:
                parts = rel_path.split(os.sep)
                if len(parts) > 1 and parts[0] != page_type:
                    continue
                if len(parts) == 1 and page_type != "root":
                    continue

            content = self.wm.read_wiki_page(rel_path)
            if content is None:
                continue

            # 标签过滤
            if tag:
                fm = self.wm.parse_frontmatter(content)
                if tag not in fm.get("tags", []):
                    continue

            # 评分
            if keyword:
                s = score_file(content, filename, tokens, query_phrase)
                if s is None:
                    continue
            else:
                s = 0.0

            fm = self.wm.parse_frontmatter(content)
            slug = os.path.splitext(rel_path)[0]
            results.append({
                "slug": slug,
                "type": fm.get("type", ""),
                "title": fm.get("title", _extract_title(content, filename)),
                "tags": fm.get("tags", []),
                "related": fm.get("related", []),
                "created": str(fm.get("created", "")),
                "updated": str(fm.get("updated", "")),
                "content": content,
                "snippet": build_snippet(content, keyword) if keyword else "",
                "score": s,
            })

        # 排序（按分数降序，同分按路径字典序）
        results.sort(key=lambda x: (-x["score"], x["slug"]))
        total = len(results)

        # 分页
        paged = results[offset: offset + limit]

        # 移除内部字段
        for r in paged:
            r.pop("score", None)

        return paged, total
