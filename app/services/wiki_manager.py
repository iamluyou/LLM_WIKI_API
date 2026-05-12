import os
import re
from typing import Optional

import frontmatter

from app.config import settings


WIKI_SUBDIRS = [
    "entities", "concepts", "sources", "queries", "comparisons",
    "synthesis", "thesis", "methodology", "findings",
]


class WikiManager:
    """Wiki 文件读写、搜索、索引管理"""

    def __init__(self, wiki_root: Optional[str] = None):
        self.wiki_root = wiki_root or settings.wiki_root
        self.wiki_dir = os.path.join(self.wiki_root, "wiki")
        self.raw_dir = os.path.join(self.wiki_root, "raw", "sources")

    # --- 读取 ---

    def read_file(self, rel_path: str) -> Optional[str]:
        """读取 wiki 目录下的文件，返回内容或 None"""
        full_path = os.path.join(self.wiki_root, rel_path)
        if not os.path.isfile(full_path):
            return None
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    def read_wiki_page(self, rel_path: str) -> Optional[str]:
        """读取 wiki/ 下的文件"""
        full_path = os.path.join(self.wiki_dir, rel_path)
        if not os.path.isfile(full_path):
            return None
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    def parse_frontmatter(self, content: str) -> dict:
        """解析 YAML frontmatter，返回元数据字典"""
        try:
            post = frontmatter.loads(content)
            return dict(post.metadata)
        except Exception:
            return {}

    def get_body(self, content: str) -> str:
        """获取 frontmatter 之后的正文"""
        try:
            post = frontmatter.loads(content)
            return post.content
        except Exception:
            return content

    def read_purpose(self) -> str:
        return self.read_file("purpose.md") or ""

    def read_schema(self) -> str:
        return self.read_file("schema.md") or ""

    def read_index(self) -> str:
        return self.read_wiki_page("index.md") or ""

    def read_overview(self) -> str:
        return self.read_wiki_page("overview.md") or ""

    # --- 列出文件 ---

    def list_wiki_files(self) -> list[str]:
        """列出 wiki/ 下所有 .md 文件的相对路径"""
        result = []
        if not os.path.isdir(self.wiki_dir):
            return result
        for root, _, files in os.walk(self.wiki_dir):
            for f in files:
                if f.endswith(".md"):
                    abs_path = os.path.join(root, f)
                    rel_path = os.path.relpath(abs_path, self.wiki_dir)
                    result.append(rel_path)
        return result

    def list_raw_sources(self) -> list[str]:
        """列出 raw/sources/ 下所有文件"""
        result = []
        if not os.path.isdir(self.raw_dir):
            return result
        for f in os.listdir(self.raw_dir):
            if f.endswith(".md"):
                result.append(f)
        return result

    # --- 搜索 ---

    def search_pages(
        self,
        keyword: str = "",
        page_type: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list, int]:
        """搜索 wiki 页面，返回 (匹配结果, 总数)

        注意：延迟导入 SearchService 以避免循环依赖
        """
        from app.services.search import SearchService

        svc = SearchService(self)
        return svc.search(keyword, page_type, tag, limit, offset)

    # --- 写入 ---

    def write_file(self, rel_path: str, content: str) -> None:
        """写入文件到 wiki_root 下"""
        full_path = os.path.join(self.wiki_root, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    def write_wiki_page(self, rel_path: str, content: str) -> None:
        """写入文件到 wiki/ 目录下"""
        full_path = os.path.join(self.wiki_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    def append_to_file(self, rel_path: str, content: str) -> None:
        """追加内容到 wiki 目录下的文件"""
        full_path = os.path.join(self.wiki_dir, rel_path)
        with open(full_path, "a", encoding="utf-8") as f:
            f.write(content)

    def write_raw_source(self, filename: str, content: str) -> str:
        """写入原始资料到 raw/sources/，返回相对路径"""
        os.makedirs(self.raw_dir, exist_ok=True)
        full_path = os.path.join(self.raw_dir, filename)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return os.path.join("raw", "sources", filename)

    # --- 统计 ---

    def get_stats(self) -> dict:
        """获取 wiki 统计信息"""
        wiki_files = self.list_wiki_files()
        by_type: dict[str, int] = {}
        for rel in wiki_files:
            parts = rel.split(os.sep)
            if len(parts) > 1:
                by_type[parts[0]] = by_type.get(parts[0], 0) + 1
            else:
                by_type["root"] = by_type.get("root", 0) + 1

        raw_sources = self.list_raw_sources()

        return {
            "total_pages": len(wiki_files),
            "by_type": by_type,
            "recent_updates": [],
            "raw_sources": len(raw_sources),
            "ingested_sources": 0,
        }


# 单例
wiki_manager = WikiManager()
