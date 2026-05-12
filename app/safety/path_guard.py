import os
import re


# 只允许 wiki/ 下的安全路径，对齐桌面版 isSafeIngestPath
_UNSAFE_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_DEVICE = re.compile(
    r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)", re.IGNORECASE
)
_WINDOWS_INVALID = re.compile(r'[<>:"|?*]')


def is_safe_ingest_path(path: str) -> bool:
    """检查路径是否安全，防止路径穿越攻击

    对齐桌面版 isSafeIngestPath，拒绝：
    - 绝对路径
    - .. 段
    - 控制字符
    - 不以 wiki/ 开头
    - Windows 非法字符/保留设备名
    """
    if not path:
        return False

    # 控制字符
    if _UNSAFE_CHARS.search(path):
        return False

    # 绝对路径
    if os.path.isabs(path):
        return False

    # .. 段
    parts = path.replace("\\", "/").split("/")
    if ".." in parts:
        return False

    # 必须以 wiki/ 开头
    normalized = path.replace("\\", "/")
    if not normalized.startswith("wiki/"):
        return False

    # Windows 驱动器号 / UNC
    if len(path) >= 2 and path[1] == ":":
        return False
    if path.startswith("\\\\"):
        return False

    # Windows 非法字符
    if _WINDOWS_INVALID.search(path):
        return False

    # Windows 保留设备名
    for part in parts:
        if _WINDOWS_DEVICE.match(part):
            return False

    return True


def sanitize_path(path: str) -> str:
    """清理路径，移除前导 wiki/ 后返回相对路径"""
    normalized = path.replace("\\", "/")
    if normalized.startswith("wiki/"):
        return normalized[5:]
    return normalized
