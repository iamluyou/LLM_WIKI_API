"""语言规则构建，对齐桌面版 languageRule"""

from typing import Optional


LANG_MAP = {
    "chinese": "Chinese (中文)",
    "english": "English",
    "japanese": "Japanese (日本語)",
    "korean": "Korean (한국어)",
    "french": "French (Français)",
    "german": "German (Deutsch)",
    "spanish": "Spanish (Español)",
}


def language_rule(source_content: Optional[str] = None, target_lang: str = "Chinese") -> str:
    """构建语言强制指令

    对齐桌面版 languageRule()：
    - 检测源内容语言
    - 生成 MANDATORY OUTPUT LANGUAGE 指令
    """
    lang_name = LANG_MAP.get(target_lang.lower(), target_lang)
    return (
        f"\n\nMANDATORY OUTPUT LANGUAGE: {lang_name}. "
        f"ALL output — including headings, analysis, explanations, and any "
        f"commentary — MUST be written in {lang_name}. "
        f"Do NOT use English (or any other language) for any part of your output "
        f"unless it is a proper noun, code, or a direct quote."
    )
