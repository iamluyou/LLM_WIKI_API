"""Source 删除流程编排，对齐桌面版 source-lifecycle.ts

完整删除流程：
  ① 删除 raw source 文件
  ② 清理 ingest cache
  ③ 扫描所有 wiki 页面，解析 frontmatter sources[]
  ④ 逐页决策（skip / keep / delete），对齐桌面版 decidePageFate()
  ⑤ 级联删除失去唯一来源的页面
  ⑥ 清理幸存页面中的引用（wikilink / related / index 条目）
  ⑦ 追加删除日志到 wiki/log.md
"""

import logging
import os
from datetime import date
from typing import List, Optional

from app.safety.ingest_cache import ingest_cache
from app.safety.project_lock import ProjectLock
from app.services.source_delete_decision import decide_page_fate
from app.services.wiki_cleanup import (
    DeletedPageInfo,
    build_deleted_keys,
    clean_index_listing,
    extract_frontmatter_title,
    parse_frontmatter_array,
    strip_deleted_wikilinks,
    write_frontmatter_array,
    normalize_wiki_ref_key,
)
from app.services.wiki_manager import wiki_manager

logger = logging.getLogger(__name__)


class SourceDeleteResult:
    """删除 source 操作的结果"""

    def __init__(self):
        self.source_deleted: bool = False
        self.deleted_wiki_pages: List[str] = []
        self.rewritten_pages: List[str] = []
        self.kept_shared_pages: int = 0


def delete_source(source_id: str, file_already_deleted: bool = False) -> SourceDeleteResult:
    """删除单个 source 及其关联的 wiki 页面

    对齐桌面版 deleteSourceFile()，在项目锁保护下执行。

    Args:
        source_id: source 文件名（含 .md 后缀）或 stem
        file_already_deleted: 文件是否已被外部删除

    Returns:
        SourceDeleteResult
    """
    logger.info(f"[SourceDelete] Starting delete for source_id={source_id}, file_already_deleted={file_already_deleted}")
    with ProjectLock():
        result = _delete_source_impl(source_id, file_already_deleted)
    logger.info(f"[SourceDelete] Done: source_deleted={result.source_deleted}, pages_deleted={len(result.deleted_wiki_pages)}, pages_rewritten={len(result.rewritten_pages)}, kept_shared={result.kept_shared_pages}")
    return result


def delete_source_batch(source_ids: List[str], file_already_deleted: bool = False) -> List[SourceDeleteResult]:
    """批量删除 source，对齐桌面版 deleteSourceFiles()"""
    results = []
    with ProjectLock():
        for sid in source_ids:
            try:
                result = _delete_source_impl(sid, file_already_deleted)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to delete source {sid}: {e}")
                r = SourceDeleteResult()
                r.source_deleted = False
                results.append(r)
    return results


def _delete_source_impl(source_id: str, file_already_deleted: bool) -> SourceDeleteResult:
    """删除实现（需在项目锁内调用）"""
    result = SourceDeleteResult()

    # ① 查找 raw 文件
    raw_filename = _find_raw_file(source_id)
    if raw_filename is None:
        if file_already_deleted:
            # 外部已删除，尝试用 source_id 作为文件名继续清理
            raw_filename = source_id if source_id.endswith(".md") else f"{source_id}.md"
        else:
            raise FileNotFoundError(f"Source not found: {source_id}")

    # ② 删除 raw source 文件
    if not file_already_deleted:
        raw_path = os.path.join(wiki_manager.raw_dir, raw_filename)
        if os.path.isfile(raw_path):
            os.remove(raw_path)
            result.source_deleted = True
        else:
            result.source_deleted = True  # 视为已删除
    else:
        result.source_deleted = True

    # ③ 清理 ingest cache
    try:
        ingest_cache.invalidate(raw_filename)
    except Exception:
        pass  # best-effort

    # ④ 扫描所有 wiki 页面，解析 sources 字段
    wiki_files = wiki_manager.list_wiki_files()
    pages_to_delete: List[str] = []
    pages_to_rewrite: dict = {}  # rel_path -> updated_sources

    for rel_path in wiki_files:
        # 跳过非内容页面
        if rel_path in ("index.md", "overview.md", "log.md"):
            continue

        content = wiki_manager.read_wiki_page(rel_path)
        if content is None:
            continue

        sources = parse_frontmatter_array(content, "sources")

        # 无 sources 字段的页面跳过
        if not sources:
            continue

        decision = decide_page_fate(sources, raw_filename)

        if decision["action"] == "skip":
            continue
        elif decision["action"] == "keep":
            pages_to_rewrite[rel_path] = decision["updated_sources"]
            result.kept_shared_pages += 1
        elif decision["action"] == "delete":
            pages_to_delete.append(rel_path)

    # ⑤ 重写 keep 页面的 sources 字段（先于删除，因为需要读取内容）
    for rel_path, updated_sources in pages_to_rewrite.items():
        content = wiki_manager.read_wiki_page(rel_path)
        if content is None:
            continue
        new_content = write_frontmatter_array(content, "sources", updated_sources)
        wiki_manager.write_wiki_page(rel_path, new_content)
        result.rewritten_pages.append(rel_path)

    # ⑥ 级联删除页面 + 引用清理
    if pages_to_delete:
        _cascade_delete_wiki_pages(pages_to_delete, result)

    # ⑦ 追加删除日志
    _append_delete_log(
        source_filename=raw_filename,
        reason="external delete" if file_already_deleted else "delete",
        wiki_pages_deleted=len(result.deleted_wiki_pages),
        shared_pages_kept=result.kept_shared_pages,
    )

    return result


def _cascade_delete_wiki_pages(page_paths: List[str], result: SourceDeleteResult) -> None:
    """级联删除 wiki 页面 + 清理引用，对齐桌面版 cascadeDeleteWikiPagesWithRefs()"""
    # 阶段1：读取元数据（删除前快照）
    infos: List[DeletedPageInfo] = []
    for rel_path in page_paths:
        content = wiki_manager.read_wiki_page(rel_path)
        slug = os.path.splitext(os.path.basename(rel_path))[0]
        title = extract_frontmatter_title(content) if content else ""
        infos.append(DeletedPageInfo(slug=slug, title=title))

    deleted_keys = build_deleted_keys(infos)

    # 阶段2：逐个删除页面
    for rel_path in page_paths:
        full_path = os.path.join(wiki_manager.wiki_dir, rel_path)
        if os.path.isfile(full_path):
            try:
                os.remove(full_path)
                result.deleted_wiki_pages.append(rel_path)
            except Exception as e:
                logger.warning(f"Failed to delete wiki page {rel_path}: {e}")

        # 删除关联媒体目录（仅 source 页面）
        slug = os.path.splitext(os.path.basename(rel_path))[0]
        if slug and not slug.startswith("."):
            media_dir = os.path.join(wiki_manager.wiki_dir, "media", slug)
            if os.path.isdir(media_dir):
                import shutil
                try:
                    shutil.rmtree(media_dir)
                except Exception:
                    pass  # best-effort

    # 阶段3：扫描所有幸存文件，清理引用
    if not deleted_keys:
        return

    surviving_files = wiki_manager.list_wiki_files()
    for rel_path in surviving_files:
        content = wiki_manager.read_wiki_page(rel_path)
        if content is None:
            continue

        updated = content
        changed = False

        # 3a: 清理 index.md 条目
        if rel_path == "index.md":
            cleaned = clean_index_listing(updated, deleted_keys)
            if cleaned != updated:
                updated = cleaned
                changed = True

        # 3b: 清理正文 wikilink
        cleaned = strip_deleted_wikilinks(updated, deleted_keys)
        if cleaned != updated:
            updated = cleaned
            changed = True

        # 3c: 清理 frontmatter related 字段
        related = parse_frontmatter_array(updated, "related")
        if related:
            filtered = [
                r for r in related
                if normalize_wiki_ref_key(r) not in deleted_keys
            ]
            if len(filtered) != len(related):
                updated = write_frontmatter_array(updated, "related", filtered)
                changed = True

        if changed:
            wiki_manager.write_wiki_page(rel_path, updated)


def _append_delete_log(
    source_filename: str,
    reason: str,
    wiki_pages_deleted: int,
    shared_pages_kept: int,
) -> None:
    """追加删除日志到 wiki/log.md，对齐桌面版 appendSourceDeleteLog()"""
    today = date.today().isoformat()
    log_entry = (
        f"\n## [{today}] {reason} | {source_filename}\n"
        f"Deleted 1 source file and {wiki_pages_deleted} wiki pages. "
        f"Kept {shared_pages_kept} shared pages.\n"
    )
    try:
        wiki_manager.append_to_file("log.md", log_entry)
    except Exception:
        pass  # best-effort


def _find_raw_file(source_id: str) -> Optional[str]:
    """查找 raw 文件名（复用 ingest_engine 的逻辑）"""
    raw_sources = wiki_manager.list_raw_sources()
    if source_id in raw_sources:
        return source_id
    for f in raw_sources:
        stem = os.path.splitext(f)[0]
        if stem == source_id or source_id in f:
            return f
    return None
