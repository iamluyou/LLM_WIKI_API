from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PageType(str, Enum):
    entity = "entity"
    concept = "concept"
    source = "source"
    query = "query"
    comparison = "comparison"
    synthesis = "synthesis"
    overview = "overview"
    thesis = "thesis"
    methodology = "methodology"
    finding = "finding"


class WikiFrontmatter(BaseModel):
    """对齐桌面版 frontmatter.ts 的通用字段"""

    type: PageType
    title: str
    tags: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    created: date
    updated: date
    sources: list[str] = Field(default_factory=list)
    prompt_version: Optional[str] = None


class SourceFrontmatter(WikiFrontmatter):
    """来源页额外字段"""

    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    url: str = ""
    venue: str = ""


class ThesisFrontmatter(WikiFrontmatter):
    """论点页额外字段"""

    confidence: Optional[str] = None  # low / medium / high
    status: Optional[str] = None  # speculative / supported / refuted / settled


class FindingFrontmatter(WikiFrontmatter):
    """发现页额外字段"""

    source: str = ""
    confidence: Optional[str] = None
    replicated: Optional[bool] = None


# --- API 请求/响应模型 ---


class PageSummary(BaseModel):
    slug: str
    type: str
    title: str
    tags: list[str]
    related: list[str]
    created: str
    updated: str
    content: str
    snippet: str = ""


class PageListResponse(BaseModel):
    total: int
    pages: list[PageSummary]


class SourceCreateRequest(BaseModel):
    title: str
    content: str
    filename: Optional[str] = None


class SourceCreateResponse(BaseModel):
    source_id: str
    filename: str
    path: str
    size_bytes: int
    ingested: bool = False


class IngestRequest(BaseModel):
    source_id: Optional[str] = None


class IngestResponse(BaseModel):
    task_id: str
    status: str
    sources: list[str]


class TaskResult(BaseModel):
    pages_created: list[str] = Field(default_factory=list)
    pages_updated: list[str] = Field(default_factory=list)
    pages_merged: int = 0
    reviews: list[dict] = Field(default_factory=list)
    cache_hit: bool = False
    tokens_used: dict[str, int] = Field(default_factory=dict)


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str  # pending / processing / completed / failed
    progress: str = ""
    result: Optional[TaskResult] = None


class QueryRequest(BaseModel):
    question: str
    save_to_wiki: bool = True
    language: str = ""


class Citation(BaseModel):
    slug: str
    title: str
    relevance: str = ""


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    wiki_page_created: str = ""
    tokens_used: dict[str, int] = Field(default_factory=dict)


class WikiInitResponse(BaseModel):
    """初始化 wiki 目录的响应"""
    wiki_root: str
    created_dirs: list[str] = Field(default_factory=list)
    created_files: list[str] = Field(default_factory=list)
    skipped_dirs: list[str] = Field(default_factory=list)
    skipped_files: list[str] = Field(default_factory=list)


class SourceDeleteResponse(BaseModel):
    """删除 source 操作的响应"""
    source_id: str
    source_deleted: bool
    deleted_wiki_pages: list[str] = Field(default_factory=list)
    rewritten_pages: list[str] = Field(default_factory=list)
    kept_shared_pages: int = 0


class StatsResponse(BaseModel):
    total_pages: int
    by_type: dict[str, int]
    recent_updates: list[str]
    raw_sources: int
    ingested_sources: int
