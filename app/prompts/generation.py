"""构建 Generation Prompt，对齐桌面版 buildGenerationPrompt"""

from app.prompts.language import language_rule


def build_generation_prompt(
    schema: str,
    purpose: str,
    index: str,
    source_file_name: str,
    analysis_result: str,
    overview: str = "",
    target_lang: str = "Chinese",
) -> list[dict]:
    """第二步：生成 Wiki 页面 prompt

    对齐桌面版 buildGenerationPrompt：
    - 系统角色：wiki maintainer
    - 极强输出格式约束（FILE/REVIEW 块）
    - 严格 frontmatter 规则
    - 7条严格输出要求
    - 注入 schema + purpose + index + overview
    - 尾部重复语言指令
    """
    lang_rule = language_rule(None, target_lang)

    system_msg = (
        "You are a wiki maintainer. Your job is to generate or update wiki "
        "pages based on an analysis of a source document. You must follow the "
        "output format strictly."
        + lang_rule
    )

    user_msg = (
        "Based on the analysis below, generate the wiki pages for the source "
        f"document \"{source_file_name}\".\n\n"
        "## Generation Requirements\n\n"
        "Generate the following in order:\n"
        "1. A source summary page → wiki/sources/<baseName>.md\n"
        "2. Entity pages → wiki/entities/\n"
        "3. Concept pages → wiki/concepts/\n"
        "4. Updated index → wiki/index.md\n"
        "5. Log entry → wiki/log.md (append only)\n"
        "6. Updated overview → wiki/overview.md\n\n"
        "## Frontmatter Rules (STRICT)\n\n"
        "1. First line of each file MUST be --- (no code fence wrapping, no 'frontmatter:' prefix)\n"
        "2. Key-value pairs, one per line\n"
        "3. Close with ---\n"
        "4. Arrays use inline form [a, b, c] (NO [[wikilink]] syntax in frontmatter)\n"
        "5. Required fields: type, title, created, updated, tags, related, sources\n\n"
        "## Output Format\n\n"
        "Each file MUST be wrapped in FILE blocks:\n\n"
        "---FILE: wiki/path/to/page.md---\n"
        "(YAML frontmatter + body)\n"
        "---END FILE---\n\n"
        "Optionally include REVIEW blocks for items needing human attention:\n\n"
        "---REVIEW: type | Title---\n"
        "Description\n"
        "OPTIONS: Create Page | Skip\n"
        "PAGES: wiki/page1.md, wiki/page2.md\n"
        "SEARCH: query 1 | query 2 | query 3\n"
        "---END REVIEW---\n\n"
        "Review types: contradiction, duplicate, missing-page, suggestion\n\n"
        "## STRICT Output Requirements\n\n"
        "1. First character must be - (the start of ---FILE:)\n"
        "2. NO preamble (e.g., 'Here are the files:')\n"
        "3. DO NOT repeat or rephrase the analysis\n"
        "4. NO tables, lists, or headings outside FILE/REVIEW blocks\n"
        "5. NO trailing commentary\n"
        "6. Separate blocks with exactly one blank line\n"
        "7. ALL content MUST be in the target output language\n\n"
        "---\n\n"
        f"## Wiki Schema\n{schema}\n\n"
        f"## Wiki Purpose\n{purpose}\n\n"
        f"## Current Wiki Index\n{index}\n\n"
        f"## Wiki Overview\n{overview}\n\n"
        "---\n\n"
        f"## Analysis Result\n{analysis_result}\n\n"
        "---\n"
        + lang_rule  # 尾部重复语言指令
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
