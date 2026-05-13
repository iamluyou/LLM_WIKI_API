"""向量搜索服务，对齐官方 embedding.ts

架构：
  - SQLite + numpy 纯 Python 实现（无外部向量数据库依赖）
  - 支持 OpenAI 兼容的 embedding API
  - chunk 级嵌入 + 页面级 max-pool 评分
  - RRF 融合 token 搜索和向量搜索
"""

import json
import logging
import math
import os
import sqlite3
from typing import Optional

import numpy as np

from app.config import settings
from app.services.text_chunker import chunk_markdown, Chunk
from app.services.wiki_manager import WikiManager

logger = logging.getLogger(__name__)

# 向量数据库路径
_VECTOR_DB_NAME = "vectors.db"


def _get_db_path(wiki_root: str) -> str:
    return os.path.join(wiki_root, ".llm-wiki", _VECTOR_DB_NAME)


def _get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            heading_path TEXT NOT NULL DEFAULT '',
            embedding BLOB NOT NULL,
            UNIQUE(page_id, chunk_index)
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_page_id ON chunks(page_id);
    """)


# ── Embedding API ───────────────────────────────────────────────────────────


async def fetch_embedding(text: str, max_retries: int = 3) -> Optional[list[float]]:
    """调用 OpenAI 兼容的 embedding API，对齐官方 fetchEmbedding

    支持自动减半重试（对齐官方 auto-halve retry）
    """
    import httpx

    endpoint = settings.effective_embedding_endpoint
    model = settings.embedding_model
    api_key = settings.effective_embedding_api_key

    if not endpoint or not model:
        return None

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    current = text
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    endpoint,
                    headers=headers,
                    json={"model": model, "input": current},
                )

            if resp.status_code == 200:
                data = resp.json()
                embedding = data.get("data", [{}])[0].get("embedding")
                if embedding:
                    return embedding
                logger.warning(f"[Embedding] Response missing data[0].embedding")
                return None

            body_text = resp.text
            # Check for oversize error
            if _looks_like_oversize_error(resp.status_code, body_text):
                if len(current) > 64 and attempt < max_retries:
                    prev_len = len(current)
                    current = current[:len(current) // 2]
                    logger.warning(
                        f"[Embedding] Auto-halving after HTTP {resp.status_code} "
                        f"at {prev_len} chars → retrying at {len(current)} chars"
                    )
                    continue
                logger.warning(f"[Embedding] Oversize error at {len(current)} chars")
                return None

            logger.warning(f"[Embedding] API {resp.status_code}: {body_text[:200]}")
            return None

        except Exception as e:
            logger.warning(f"[Embedding] Error: {e}")
            return None

    return None


def _looks_like_oversize_error(status: int, body: str) -> bool:
    if status == 413:
        return True
    lower = body.lower()
    return any(kw in lower for kw in [
        "too long", "maximum context", "max_tokens", "max tokens",
        "context length", "token limit", "exceeds", "input length",
    ])


# ── Vector DB operations ────────────────────────────────────────────────────


def _embedding_to_blob(vec: list[float]) -> bytes:
    return np.array(vec, dtype=np.float32).tobytes()


def _blob_to_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def upsert_chunks(wiki_root: str, page_id: str, chunks_data: list[dict]):
    """写入页面的 chunk 向量，对齐官方 vector_upsert_chunks"""
    db_path = _get_db_path(wiki_root)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = _get_connection(db_path)
    try:
        _init_db(conn)
        # Delete existing chunks for this page
        conn.execute("DELETE FROM chunks WHERE page_id = ?", (page_id,))
        # Insert new chunks
        for c in chunks_data:
            conn.execute(
                "INSERT INTO chunks (page_id, chunk_index, chunk_text, heading_path, embedding) "
                "VALUES (?, ?, ?, ?, ?)",
                (page_id, c["chunk_index"], c["chunk_text"], c["heading_path"],
                 _embedding_to_blob(c["embedding"])),
            )
        conn.commit()
    finally:
        conn.close()


def delete_page(wiki_root: str, page_id: str):
    """删除页面的所有 chunk 向量"""
    db_path = _get_db_path(wiki_root)
    if not os.path.exists(db_path):
        return
    conn = _get_connection(db_path)
    try:
        conn.execute("DELETE FROM chunks WHERE page_id = ?", (page_id,))
        conn.commit()
    finally:
        conn.close()


def vector_search(wiki_root: str, query_embedding: list[float], top_k: int = 30) -> list[dict]:
    """向量搜索，对齐官方 vector_search_chunks + page-level max-pool 评分"""
    db_path = _get_db_path(wiki_root)
    if not os.path.exists(db_path):
        return []

    query_vec = np.array(query_embedding, dtype=np.float32)
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return []
    query_vec = query_vec / query_norm

    conn = _get_connection(db_path)
    try:
        # Fetch all chunks (in-memory cosine similarity)
        cursor = conn.execute(
            "SELECT page_id, chunk_index, chunk_text, heading_path, embedding FROM chunks"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    # Compute cosine similarity for all chunks
    chunk_scores: list[tuple[str, int, str, str, float]] = []
    for page_id, chunk_idx, chunk_text, heading_path, emb_blob in rows:
        vec = _blob_to_embedding(emb_blob)
        vec_norm = np.linalg.norm(vec)
        if vec_norm == 0:
            continue
        score = float(np.dot(query_vec, vec / vec_norm))
        chunk_scores.append((page_id, chunk_idx, chunk_text, heading_path, score))

    # Sort by score descending, take top_k * 3
    chunk_scores.sort(key=lambda x: -x[4])
    chunk_scores = chunk_scores[:top_k]

    # Group by page_id, max-pool + weighted tail (对齐官方 searchByEmbedding)
    by_page: dict[str, list[tuple[int, str, str, float]]] = {}
    for page_id, chunk_idx, chunk_text, heading_path, score in chunk_scores:
        if page_id not in by_page:
            by_page[page_id] = []
        by_page[page_id].append((chunk_idx, chunk_text, heading_path, score))

    ranked: list[dict] = []
    for page_id, chunks in by_page.items():
        chunks.sort(key=lambda x: -x[3])
        top_score = chunks[0][3]
        tail_sum = sum(c[3] for c in chunks[1:])
        # Blended score: top + min(tail * 0.3, 1 - top)
        blended = top_score + min(tail_sum * 0.3, max(0, 1 - top_score))
        matched_chunks = [
            {"text": c[1], "heading_path": c[2], "score": c[3]}
            for c in chunks[:3]
        ]
        ranked.append({
            "id": page_id,
            "score": blended,
            "matched_chunks": matched_chunks,
        })

    ranked.sort(key=lambda x: -x["score"])
    return ranked[:10]


def count_chunks(wiki_root: str) -> int:
    db_path = _get_db_path(wiki_root)
    if not os.path.exists(db_path):
        return 0
    conn = _get_connection(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


# ── Page embedding (called after ingest) ────────────────────────────────────


async def embed_page(wiki_root: str, page_id: str, title: str, content: str):
    """嵌入单个页面，对齐官方 embedPage"""
    if not settings.embedding_enabled or not settings.embedding_model:
        return

    chunks = chunk_markdown(content)
    if not chunks:
        return

    rows: list[dict] = []
    for chunk in chunks:
        # Enrich text for embedding (title + heading + content)
        parts = []
        if title.strip():
            parts.append(title.strip())
        if chunk.heading_path.strip():
            parts.append(chunk.heading_path.strip())
        parts.append(chunk.text.strip())
        embed_text = "\n\n".join(parts)

        vec = await fetch_embedding(embed_text)
        if vec:
            rows.append({
                "chunk_index": chunk.index,
                "chunk_text": chunk.text,
                "heading_path": chunk.heading_path,
                "embedding": vec,
            })

    if rows:
        upsert_chunks(wiki_root, page_id, rows)
        logger.info(f"[Embedding] Indexed '{page_id}': {len(rows)}/{len(chunks)} chunks")
    else:
        logger.warning(f"[Embedding] No chunks indexed for '{page_id}'")


async def embed_all_pages(wiki_manager: WikiManager) -> int:
    """嵌入所有 wiki 页面，对齐官方 embedAllPages"""
    if not settings.embedding_enabled or not settings.embedding_model:
        return 0

    wiki_files = wiki_manager.list_wiki_files()
    skip_ids = {"index", "log", "overview", "purpose", "schema"}
    done = 0

    for rel_path in wiki_files:
        page_id = os.path.splitext(rel_path)[0]
        # Skip structural pages
        if os.path.basename(rel_path).replace(".md", "") in skip_ids:
            continue

        content = wiki_manager.read_wiki_page(rel_path)
        if content is None:
            continue

        fm = wiki_manager.parse_frontmatter(content)
        title = fm.get("title", os.path.basename(rel_path).replace(".md", "").replace("-", " "))

        await embed_page(wiki_manager.wiki_root, page_id, title, content)
        done += 1

    logger.info(f"[Embedding] Embedded {done} pages")
    return done


# ── Vector search entry point ───────────────────────────────────────────────


async def search_by_embedding(wiki_root: str, query: str, top_k: int = 10) -> list[dict]:
    """向量搜索入口，对齐官方 searchByEmbedding"""
    if not settings.embedding_enabled or not settings.embedding_model:
        return []

    query_emb = await fetch_embedding(query)
    if not query_emb:
        return []

    return vector_search(wiki_root, query_emb, top_k * 3)
