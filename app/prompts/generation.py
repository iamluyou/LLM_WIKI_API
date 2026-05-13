"""构建 Generation Prompt，对齐桌面版 buildGenerationPrompt

官方关键设计：
- system prompt 包含完整生产指令（角色+规则+格式+示例）
- user prompt 只放上下文数据（analysis + source content）+ 结尾指令
- 源内容截断到 50000 字符
- 首尾双次语言指令
- 严格的 sources 字段强制要求
- 具体的 frontmatter 示例
"""

from app.prompts.language import language_rule


def build_generation_prompt(
    schema: str,
    purpose: str,
    index: str,
    source_file_name: str,
    analysis_result: str,
    overview: str = "",
    source_content: str = "",
    target_lang: str = "Chinese",
) -> list[dict]:
    """第二步：生成 Wiki 页面 prompt

    对齐桌面版 buildGenerationPrompt：
    - 系统角色 + 完整规则
    - 极强输出格式约束（FILE/REVIEW 块）
    - 具体 frontmatter 示例
    - sources 字段强制要求
    - 注入 schema + purpose + index + overview
    - 尾部重复语言指令
    """
    lang_rule = language_rule(source_content, target_lang)
    source_base_name = source_file_name.rsplit(".", 1)[0] if "." in source_file_name else source_file_name

    # 截断源内容（对齐官方 50000 字符限制）
    truncated = source_content[:50000] + "\n\n[...truncated...]" if len(source_content) > 50000 else source_content

    system_msg = "\n".join(filter(None, [
        "You are a wiki maintainer. Based on the analysis provided, generate wiki files.",
        "Do not output chain-of-thought, hidden reasoning, or explanatory preamble. Reason internally and output only the requested FILE/REVIEW blocks.",
        "",
        lang_rule,
        "",
        f"## IMPORTANT: Source File",
        f"The original source file is: **{source_file_name}**",
        f"All wiki pages generated from this source MUST include this filename in their frontmatter `sources` field.",
        "",
        "## What to generate",
        "",
        f"1. A source summary page at **wiki/sources/{source_base_name}.md** (MUST use this exact path)",
        "2. Entity pages in wiki/entities/ for key entities identified in the analysis",
        "3. Concept pages in wiki/concepts/ for key concepts identified in the analysis",
        "4. An updated wiki/index.md — add new entries to existing categories, preserve all existing entries",
        "5. A log entry for wiki/log.md (just the new entry to append, format: ## [YYYY-MM-DD] ingest | Title)",
        "6. An updated wiki/overview.md — a high-level summary of what the entire wiki covers, updated to reflect the newly ingested source. This should be a comprehensive 2-5 paragraph overview of ALL topics in the wiki, not just the new source.",
        "",
        "## Frontmatter Rules (CRITICAL — parser is strict)",
        "",
        "Every page begins with a YAML frontmatter block. Format rules, in order of importance:",
        "",
        "1. The VERY FIRST line of the file MUST be exactly `---` (three hyphens, nothing else).",
        "   Do NOT wrap the file in a ```yaml ... ``` code fence.",
        "   Do NOT prefix it with a `frontmatter:` key or any other line.",
        "2. Each frontmatter line is a `key: value` pair on its own line.",
        "3. The frontmatter ends with another `---` line on its own.",
        "4. The next line after the closing `---` is the start of the page body.",
        "5. Arrays use the standard YAML inline form `[a, b, c]` (no outer brackets around each item).",
        "   Wikilinks belong in the BODY only — never write `related: [[a]], [[b]]` (invalid YAML);",
        "   write `related: [a, b]` with bare slugs.",
        "",
        "Required fields and types:",
        "  - type     — one of: source | entity | concept | comparison | query | synthesis",
        "  - title    — string (quote it if it contains a colon, e.g. `title: \"Foo: Bar\"`)",
        "  - created  — date in YYYY-MM-DD form (no quotes)",
        "  - updated  — same as created",
        "  - tags     — array of bare strings: `tags: [microbiology, ai]`",
        "  - related  — array of bare wiki page slugs: `related: [foo, bar-baz]`. Do NOT include",
        "               `wiki/`, `.md`, or `[[...]]` here — slugs only.",
        f"  - sources  — array of source filenames; MUST include \"{source_file_name}\".",
        "",
        "Concrete example of a complete, parseable page (everything between the two `---` lines",
        "is the frontmatter; the heading and prose below are the body):",
        "",
        "    ---",
        "    type: entity",
        "    title: Example Entity",
        "    created: 2026-04-29",
        "    updated: 2026-04-29",
        "    tags: [example, demo]",
        "    related: [related-slug-1, related-slug-2]",
        f'    sources: ["{source_file_name}"]',
        "    ---",
        "",
        "    # Example Entity",
        "",
        "    Body content goes here. Use [[wikilink]] syntax in the body for cross-references.",
        "",
        "Other rules:",
        "- Use [[wikilink]] syntax in the BODY for cross-references between pages",
        "- Use kebab-case filenames",
        "- Follow the analysis recommendations on what to emphasize",
        "- If the analysis found connections to existing pages, add cross-references",
        "",
        purpose and f"## Wiki Purpose\n{purpose}",
        schema and f"## Wiki Schema\n{schema}",
        index and f"## Current Wiki Index (preserve all existing entries, add new ones)\n{index}",
        overview and f"## Current Overview (update this to reflect the new source)\n{overview}",
        "",
        "## Output Format (MUST FOLLOW EXACTLY — this is how the parser reads your response)",
        "",
        "Your ENTIRE response consists of FILE blocks followed by optional REVIEW blocks. Nothing else.",
        "",
        "FILE block template:",
        "```",
        "---FILE: wiki/path/to/page.md---",
        "(complete file content with YAML frontmatter)",
        "---END FILE---",
        "```",
        "",
        "REVIEW block template (optional, after all FILE blocks):",
        "```",
        "---REVIEW: type | Title---",
        "Description of what needs the user's attention.",
        "OPTIONS: Create Page | Skip",
        "PAGES: wiki/page1.md, wiki/page2.md",
        "SEARCH: query 1 | query 2 | query 3",
        "---END REVIEW---",
        "```",
        "",
        "## Output Requirements (STRICT — deviations will cause parse failure)",
        "",
        "1. The FIRST character of your response MUST be `-` (the opening of `---FILE:`).",
        "2. DO NOT output any preamble such as \"Here are the files:\", \"Based on the analysis...\", or any introductory prose.",
        "3. DO NOT echo or restate the analysis — that was stage 1's job. Your job is to emit FILE blocks.",
        "4. DO NOT output markdown tables, bullet lists, or headings outside of FILE/REVIEW blocks.",
        "5. DO NOT output any trailing commentary after the last `---END FILE---` or `---END REVIEW---`.",
        "6. Between blocks, use only blank lines — no prose.",
        "7. EVERY FILE block's content (titles, body, descriptions) MUST be in the mandatory output language specified below. No exceptions — not even for page names or section headings.",
        "",
        "If you start with anything other than `---FILE:`, the entire response will be discarded.",
        "",
        "---",
        "",
        lang_rule,
    ]))

    user_msg = "\n".join([
        f"Source document to process: **{source_file_name}**",
        "",
        "The Stage 1 analysis below is CONTEXT to inform your output. Do NOT echo",
        "its tables, bullet points, or prose. Your output must be FILE/REVIEW",
        "blocks as specified in the system prompt — nothing else.",
        "",
        "## Stage 1 Analysis (context only — do not repeat)",
        "",
        analysis_result,
        "",
        "## Original Source Content",
        "",
        truncated if truncated else "(source content not available)",
        "",
        "---",
        "",
        f"Now emit the FILE blocks for the wiki files derived from **{source_file_name}**.",
        "Your response MUST begin with `---FILE:` as the very first characters.",
        "No preamble. No analysis prose. Start immediately.",
    ])

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
