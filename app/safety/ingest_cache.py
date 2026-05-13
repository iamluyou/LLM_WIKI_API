import hashlib
import json
import os
from typing import Optional

from app.config import settings


class IngestCache:
    """SHA256 增量缓存，对齐桌面版 ingest-cache.ts

    未变化的 source 直接跳过 LLM 调用。
    """

    def __init__(self, wiki_root: Optional[str] = None):
        self.wiki_root = wiki_root or settings.wiki_root
        self.cache_dir = os.path.join(self.wiki_root, ".llm-wiki", "ingest-cache")
        os.makedirs(self.cache_dir, exist_ok=True)

    def _cache_path(self, filename: str) -> str:
        safe_name = filename.replace("/", "_").replace("\\", "_")
        return os.path.join(self.cache_dir, f"{safe_name}.json")

    def check(self, filename: str, content: str) -> bool:
        """检查 source 是否已缓存（SHA256 比对 + 文件存在性校验）

        返回 True 表示缓存命中，应跳过 LLM 调用。

        对齐官方 ingest-cache.ts：缓存命中时必须验证所有
        files_written 仍存在于磁盘，否则视为缓存失效。
        历史原因：直接信任缓存列表会导致幽灵条目（磁盘文件
        已被删除，但缓存仍声称其存在）。
        """
        cache_file = self._cache_path(filename)
        if not os.path.isfile(cache_file):
            return False

        current_hash = hashlib.sha256(content.encode()).hexdigest()
        try:
            with open(cache_file, "r") as f:
                cached = json.load(f)
            if cached.get("sha256") != current_hash:
                return False
        except Exception:
            return False

        # 校验所有生成文件是否仍存在于磁盘
        files_written = cached.get("files_written", [])
        for rel_path in files_written:
            full_path = os.path.join(self.wiki_root, "wiki", rel_path)
            if not os.path.isfile(full_path):
                return False

        return True

    def save(self, filename: str, content: str, result: dict) -> None:
        """保存缓存（仅在没有硬失败时调用）

        对齐官方：保存 files_written 列表，用于缓存命中时校验文件存在性。
        """
        cache_file = self._cache_path(filename)
        current_hash = hashlib.sha256(content.encode()).hexdigest()

        # 从 result 中提取所有生成/更新的文件路径
        files_written = list(set(
            result.get("pages_created", []) + result.get("pages_updated", [])
        ))

        try:
            with open(cache_file, "w") as f:
                json.dump({
                    "sha256": current_hash,
                    "files_written": files_written,
                    "timestamp": __import__("time").time(),
                }, f, ensure_ascii=False)
        except Exception:
            pass  # best-effort

    def invalidate(self, filename: str) -> None:
        """使缓存失效"""
        cache_file = self._cache_path(filename)
        if os.path.isfile(cache_file):
            os.remove(cache_file)


ingest_cache = IngestCache()
