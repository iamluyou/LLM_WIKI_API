"""构建 Page Merger Prompt，对齐桌面版 buildPageMerger"""

from app.prompts.language import language_rule


def build_page_merger_prompt(
    existing_content: str,
    incoming_content: str,
    source_file_name: str,
    target_lang: str = "Chinese",
) -> list[dict]:
    """页面合并 prompt

    对齐桌面版 buildPageMerger：
    - 保留两个版本的所有事实声明
    - 消除冗余
    - 重新组织为逻辑结构
    - 保持 [[wikilink]] 完整
    - 输出完整文件（frontmatter + body）
    """
    lang_rule = language_rule(None, target_lang)

    system_msg = (
        "You are a wiki page merger. You combine two versions of a wiki page "
        "into a single coherent version."
        + lang_rule
    )

    user_msg = (
        f"Merge the following two versions of a wiki page (source: {source_file_name}).\n\n"
        "## Rules\n"
        "- Preserve ALL factual claims from both versions\n"
        "- Eliminate redundancy (do not repeat the same fact twice)\n"
        "- Reorganize into a logical structure (NOT a simple concatenation)\n"
        "- Preserve all [[wikilink]] references from both versions\n"
        "- Output the complete merged file including frontmatter and body\n"
        "- First character of output must be -\n\n"
        f"## Existing Version\n{existing_content}\n\n"
        f"## Incoming Version\n{incoming_content}\n"
        + lang_rule
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
