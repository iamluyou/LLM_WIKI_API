import os
from typing import Optional

from filelock import FileLock

from app.config import settings


class ProjectLock:
    """项目级互斥锁，对齐桌面版 withProjectLock

    使用 filelock 实现跨进程互斥，保护 wiki/ 目录的所有写入操作。
    """

    def __init__(self, wiki_root: Optional[str] = None):
        self.wiki_root = wiki_root or settings.wiki_root
        self._lock_dir = os.path.join(self.wiki_root, ".llm-wiki")
        self._lock_path = os.path.join(self._lock_dir, ".project.lock")
        os.makedirs(self._lock_dir, exist_ok=True)

    def acquire(self, timeout: int = 300) -> FileLock:
        lock = FileLock(self._lock_path, timeout=timeout)
        lock.acquire()
        return lock

    def __enter__(self):
        self._lock = self.acquire()
        return self

    def __exit__(self, *args):
        if hasattr(self, "_lock"):
            self._lock.release()


def with_project_lock(wiki_root: Optional[str] = None, timeout: int = 300):
    """上下文管理器：项目级文件锁"""
    return ProjectLock(wiki_root)
