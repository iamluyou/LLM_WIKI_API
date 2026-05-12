import re
from typing import Optional


def detect_script_family(text: str) -> str:
    """检测文本的主要脚本族

    返回: 'cjk' | 'latin' | 'arabic' | 'cyrillic' | 'other'
    """
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f]", text))
    latin = len(re.findall(r"[a-zA-Z]", text))
    arabic = len(re.findall(r"[\u0600-\u06ff]", text))
    cyrillic = len(re.findall(r"[\u0400-\u04ff]", text))

    scores = {"cjk": cjk, "latin": latin, "arabic": arabic, "cyrillic": cyrillic}
    if max(scores.values()) == 0:
        return "other"
    return max(scores, key=scores.get)


def content_matches_target_language(content: str, target_lang: str) -> bool:
    """检查内容是否与目标输出语言一致

    对齐桌面版 contentMatchesTargetLanguage：
    - 剥离 frontmatter 和代码/数学块
    - 检测正文脚本族
    - 比较目标语言
    """
    # 剥离 frontmatter
    body = re.sub(r"^---\n[\s\S]*?\n---\n", "", content, count=1)
    # 剥离代码块和数学块
    body = re.sub(r"```[\s\S]*?```", "", body)
    body = re.sub(r"\$\$[\s\S]*?\$\$", "", body)
    body = re.sub(r"\$[^$]+\$", "", body)

    if not body.strip():
        return True  # 空内容视为通过

    script = detect_script_family(body)

    # 目标语言到脚本族映射
    lang_script_map = {
        "chinese": "cjk",
        "japanese": "cjk",
        "korean": "cjk",
        "english": "latin",
        "french": "latin",
        "german": "latin",
        "spanish": "latin",
        "arabic": "arabic",
        "russian": "cyrillic",
    }

    target_lower = target_lang.lower()
    expected = lang_script_map.get(target_lower, None)

    if expected is None:
        return True  # 未知目标语言，不检查

    return script == expected
