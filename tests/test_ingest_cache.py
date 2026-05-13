"""测试 ingest_cache SHA256 缓存 + 文件存在性校验"""

import hashlib
import json
import os

import pytest

from app.safety.ingest_cache import IngestCache


class TestIngestCacheBasic:
    def test_cache_miss(self, tmp_path):
        cache = IngestCache(wiki_root=str(tmp_path))
        assert cache.check("test.md", "content") is False

    def test_cache_hit(self, tmp_path):
        cache = IngestCache(wiki_root=str(tmp_path))
        cache.save("test.md", "content", {"pages_created": [], "pages_updated": []})
        assert cache.check("test.md", "content") is True

    def test_cache_miss_after_content_change(self, tmp_path):
        cache = IngestCache(wiki_root=str(tmp_path))
        cache.save("test.md", "old content", {"pages_created": [], "pages_updated": []})
        assert cache.check("test.md", "new content") is False

    def test_invalidate(self, tmp_path):
        cache = IngestCache(wiki_root=str(tmp_path))
        cache.save("test.md", "content", {"pages_created": [], "pages_updated": []})
        cache.invalidate("test.md")
        assert cache.check("test.md", "content") is False


class TestCacheFileExistenceValidation:
    """对齐官方 ingest-cache.ts：缓存命中时验证 files_written 是否仍存在于磁盘"""

    def test_cache_hit_when_files_exist(self, tmp_path):
        """所有生成文件存在时缓存命中"""
        cache = IngestCache(wiki_root=str(tmp_path))

        # 创建 wiki 目录和文件
        wiki_dir = os.path.join(str(tmp_path), "wiki", "entities")
        os.makedirs(wiki_dir, exist_ok=True)
        with open(os.path.join(wiki_dir, "test.md"), "w") as f:
            f.write("---\ntype: entity\n---\nBody")

        cache.save("source.md", "content", {
            "pages_created": ["entities/test.md"],
            "pages_updated": [],
        })
        assert cache.check("source.md", "content") is True

    def test_cache_miss_when_file_deleted(self, tmp_path):
        """生成文件被删除后缓存失效（防止幽灵条目）"""
        cache = IngestCache(wiki_root=str(tmp_path))

        # 创建 wiki 目录和文件
        wiki_dir = os.path.join(str(tmp_path), "wiki", "entities")
        os.makedirs(wiki_dir, exist_ok=True)
        file_path = os.path.join(wiki_dir, "test.md")
        with open(file_path, "w") as f:
            f.write("---\ntype: entity\n---\nBody")

        cache.save("source.md", "content", {
            "pages_created": ["entities/test.md"],
            "pages_updated": [],
        })

        # 验证缓存命中
        assert cache.check("source.md", "content") is True

        # 删除生成文件
        os.remove(file_path)

        # 缓存应失效
        assert cache.check("source.md", "content") is False

    def test_cache_miss_when_any_file_missing(self, tmp_path):
        """任一生成文件缺失时缓存失效"""
        cache = IngestCache(wiki_root=str(tmp_path))

        wiki_dir = os.path.join(str(tmp_path), "wiki", "concepts")
        os.makedirs(wiki_dir, exist_ok=True)
        # 只创建一个文件
        with open(os.path.join(wiki_dir, "a.md"), "w") as f:
            f.write("---\n---\nA")

        cache.save("source.md", "content", {
            "pages_created": ["concepts/a.md"],
            "pages_updated": ["concepts/b.md"],  # b.md 不存在
        })

        # 应失效，因为 b.md 不存在
        assert cache.check("source.md", "content") is False

    def test_cache_hit_empty_files_written(self, tmp_path):
        """无 files_written 时（空结果），缓存仍可命中"""
        cache = IngestCache(wiki_root=str(tmp_path))
        cache.save("source.md", "content", {
            "pages_created": [],
            "pages_updated": [],
        })
        assert cache.check("source.md", "content") is True

    def test_cache_stores_files_written(self, tmp_path):
        """验证 save 保存了 files_written 字段"""
        cache = IngestCache(wiki_root=str(tmp_path))
        cache.save("source.md", "content", {
            "pages_created": ["entities/a.md"],
            "pages_updated": ["concepts/b.md", "index.md"],
        })

        cache_file = cache._cache_path("source.md")
        with open(cache_file, "r") as f:
            cached = json.load(f)

        # 去重后的文件列表
        assert "entities/a.md" in cached["files_written"]
        assert "concepts/b.md" in cached["files_written"]
        assert "index.md" in cached["files_written"]
        assert "timestamp" in cached
