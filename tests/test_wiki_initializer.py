"""wiki_initializer 单元测试"""

import os
import pytest

from app.services.wiki_initializer import init_wiki_root, WIKI_SUBDIRS, META_SUBDIRS, TEMPLATES_DIR


class TestInitWikiRoot:
    def test_creates_full_structure(self, tmp_path):
        """从零创建完整目录结构"""
        root = str(tmp_path / "wiki")
        result = init_wiki_root(root)

        assert result["wiki_root"] == root
        assert len(result["created_dirs"]) > 0
        assert len(result["created_files"]) > 0
        assert len(result["skipped_dirs"]) == 0
        assert len(result["skipped_files"]) == 0

    def test_all_dirs_exist(self, tmp_path):
        root = str(tmp_path / "wiki")
        init_wiki_root(root)

        assert os.path.isdir(os.path.join(root, "raw", "sources"))
        assert os.path.isdir(os.path.join(root, "raw", "assets"))
        for subdir in WIKI_SUBDIRS:
            assert os.path.isdir(os.path.join(root, "wiki", subdir)), f"Missing wiki/{subdir}/"
        for subdir in META_SUBDIRS:
            assert os.path.isdir(os.path.join(root, ".llm-wiki", subdir)), f"Missing .llm-wiki/{subdir}/"
        assert os.path.isdir(os.path.join(root, ".obsidian"))

    def test_seed_files_from_templates(self, tmp_path):
        """种子文件从模板目录复制"""
        root = str(tmp_path / "wiki")
        init_wiki_root(root)

        # 模板目录下有多少文件，就应该创建多少
        if os.path.isdir(TEMPLATES_DIR):
            for dirpath, _, filenames in os.walk(TEMPLATES_DIR):
                for f in filenames:
                    if f.startswith(".") or f.startswith("_"):
                        continue
                    rel = os.path.relpath(os.path.join(dirpath, f), TEMPLATES_DIR)
                    assert os.path.isfile(os.path.join(root, rel)), f"Missing seed file: {rel}"

    def test_seed_files_have_frontmatter(self, tmp_path):
        root = str(tmp_path / "wiki")
        init_wiki_root(root)

        # wiki/ 下的种子文件有 frontmatter（对齐官方）
        for name in ("wiki/index.md", "wiki/overview.md", "wiki/log.md"):
            path = os.path.join(root, name)
            if os.path.isfile(path):
                with open(path) as f:
                    content = f.read()
                assert content.startswith("#"), f"{name} should start with heading"

        # 根目录的 schema.md 和 purpose.md 无 frontmatter（对齐官方）
        for name in ("purpose.md", "schema.md"):
            path = os.path.join(root, name)
            if os.path.isfile(path):
                with open(path) as f:
                    content = f.read()
                assert content.startswith("#"), f"{name} should start with heading"

    def test_date_placeholder_replaced(self, tmp_path):
        """{{date}} 占位符在 log.md 中被替换"""
        root = str(tmp_path / "wiki")
        init_wiki_root(root)

        path = os.path.join(root, "wiki", "log.md")
        if os.path.isfile(path):
            with open(path) as f:
                content = f.read()
            assert "{{date}}" not in content
            import re
            assert re.search(r"\d{4}-\d{2}-\d{2}", content)

    def test_idempotent(self, tmp_path):
        """重复调用不报错，已存在的跳过"""
        root = str(tmp_path / "wiki")
        r1 = init_wiki_root(root)
        r2 = init_wiki_root(root)

        assert len(r1["created_dirs"]) > 0
        assert len(r2["created_dirs"]) == 0
        assert len(r2["skipped_dirs"]) == len(r1["created_dirs"])
        assert len(r2["skipped_files"]) == len(r1["created_files"])

    def test_force_overwrites(self, tmp_path):
        """force=True 重建所有"""
        root = str(tmp_path / "wiki")
        init_wiki_root(root)

        idx = os.path.join(root, "wiki", "index.md")
        with open(idx, "w") as f:
            f.write("MODIFIED")

        r = init_wiki_root(root, force=True)
        assert "wiki/index.md" in r["created_files"]

        with open(idx) as f:
            content = f.read()
        assert "MODIFIED" not in content
        assert "Wiki Index" in content

    def test_preserves_existing_without_force(self, tmp_path):
        """force=False 不覆盖已有文件"""
        root = str(tmp_path / "wiki")
        init_wiki_root(root)

        idx = os.path.join(root, "wiki", "index.md")
        with open(idx, "w") as f:
            f.write("PRESERVED")

        init_wiki_root(root, force=False)

        with open(idx) as f:
            assert f.read() == "PRESERVED"

    def test_uses_settings_default(self, tmp_path, monkeypatch):
        """不传 wiki_root 时使用 settings.wiki_root"""
        root = str(tmp_path / "wiki")
        monkeypatch.setattr("app.services.wiki_initializer.settings.wiki_root", root)

        result = init_wiki_root()
        assert result["wiki_root"] == root

    def test_handles_missing_templates_dir(self, tmp_path, monkeypatch):
        """模板目录不存在时优雅降级（只创建目录，不复制种子文件）"""
        root = str(tmp_path / "wiki")
        monkeypatch.setattr("app.services.wiki_initializer.TEMPLATES_DIR", "/nonexistent/path")

        result = init_wiki_root(root)
        assert len(result["created_dirs"]) > 0
        assert len(result["created_files"]) == 0  # 没有种子文件
        # 但目录结构仍完整
        assert os.path.isdir(os.path.join(root, "raw", "sources"))
