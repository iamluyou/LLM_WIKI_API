"""Wiki 目录初始化 — 从模板目录创建 wiki_root 完整目录结构"""

import os
import logging
from datetime import datetime
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# 模板目录（与本项目一起分发）
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "wiki_root")

# wiki/ 下的子目录（对齐桌面版，无模板文件的纯目录）
WIKI_SUBDIRS = [
    "entities", "concepts", "sources", "queries", "comparisons",
    "synthesis", "thesis", "methodology", "findings",
]

# .llm-wiki/ 下的子目录
META_SUBDIRS = [
    "page-history",
    "ingest-cache",
]


def _render_template(src_path: str, date_str: str) -> str:
    """读取模板文件并替换 {{date}} 占位符"""
    with open(src_path, "r", encoding="utf-8") as f:
        content = f.read()
    return content.replace("{{date}}", date_str)


def init_wiki_root(wiki_root: Optional[str] = None, force: bool = False) -> dict:
    """初始化 wiki_root 目录结构。

    从 app/templates/wiki_root/ 复制种子文件到目标目录，
    并创建所有必需的子目录。

    Args:
        wiki_root: 目标路径，默认使用 settings.wiki_root
        force: 是否强制重建已存在的目录/文件

    Returns:
        创建结果摘要
    """
    root = wiki_root or settings.wiki_root
    date_str = datetime.now().strftime("%Y-%m-%d")
    created_dirs = []
    created_files = []
    skipped_dirs = []
    skipped_files = []

    # 1. 创建顶层目录
    os.makedirs(root, exist_ok=True)
    logger.info(f"[Init] Starting wiki_root initialization: {root} (force={force})")

    # 2. 创建 raw/sources/ 和 raw/assets/
    for raw_sub in ("sources", "assets"):
        path = os.path.join(root, "raw", raw_sub)
        if not os.path.isdir(path) or force:
            os.makedirs(path, exist_ok=True)
            created_dirs.append(f"raw/{raw_sub}/")
        else:
            skipped_dirs.append(f"raw/{raw_sub}/")

    # 3. 创建 wiki/ 子目录（纯目录，无模板文件）
    for subdir in WIKI_SUBDIRS:
        path = os.path.join(root, "wiki", subdir)
        if not os.path.isdir(path) or force:
            os.makedirs(path, exist_ok=True)
            created_dirs.append(f"wiki/{subdir}/")
        else:
            skipped_dirs.append(f"wiki/{subdir}/")

    # 4. 创建 .llm-wiki/ 子目录
    for subdir in META_SUBDIRS:
        path = os.path.join(root, ".llm-wiki", subdir)
        if not os.path.isdir(path) or force:
            os.makedirs(path, exist_ok=True)
            created_dirs.append(f".llm-wiki/{subdir}/")
        else:
            skipped_dirs.append(f".llm-wiki/{subdir}/")

    # 5. 从模板目录复制种子文件
    #    注意：.obsidian/ 下的 JSON 配置文件需要复制，仅跳过模板中以 _ 开头的临时文件
    if not os.path.isdir(TEMPLATES_DIR):
        logger.warning(f"Templates directory not found: {TEMPLATES_DIR}, skipping seed files")
    else:
        for dirpath, _, filenames in os.walk(TEMPLATES_DIR):
            for filename in filenames:
                if filename.startswith("_"):
                    continue
                src = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(src, TEMPLATES_DIR)
                dst = os.path.join(root, rel_path)

                if not os.path.isfile(dst) or force:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if src.endswith(".md"):
                        content = _render_template(src, date_str)
                    else:
                        with open(src, "r", encoding="utf-8") as f:
                            content = f.read()
                    with open(dst, "w", encoding="utf-8") as f:
                        f.write(content)
                    created_files.append(rel_path)
                else:
                    skipped_files.append(rel_path)

    result = {
        "wiki_root": root,
        "created_dirs": created_dirs,
        "created_files": created_files,
        "skipped_dirs": skipped_dirs,
        "skipped_files": skipped_files,
    }
    logger.info(f"Wiki root initialized: {len(created_dirs)} dirs, {len(created_files)} files created")
    return result
