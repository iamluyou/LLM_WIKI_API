"""构建 Analysis Prompt，对齐桌面版 buildAnalysisPrompt"""

from app.prompts.language import language_rule


def build_analysis_prompt(
    purpose: str,
    index: str,
    source_content: str,
    target_lang: str = "Chinese",
) -> list[dict]:
    """第一步：分析资料 prompt

    对齐桌面版 buildAnalysisPrompt：
    - 系统角色：expert research analyst
    - 6大分析维度
    - 注入 purpose + index
    - 反链式思维指令
    - 首尾双次语言指令
    """
    lang_rule = language_rule(source_content, target_lang)

    system_msg = (
        "You are an expert research analyst. Your job is to carefully analyze "
        "a source document and extract structured insights that will be used to "
        "update a knowledge wiki."
        + lang_rule
    )

    user_msg = (
        "Analyze the following source document. Provide a thorough, structured "
        "analysis covering these dimensions:\n\n"
        "## Key Entities\n"
        "Identify all named entities (people, organizations, products, tools, "
        "datasets). For each, note its role/importance and whether it already "
        "exists in the wiki (based on the index below).\n\n"
        "## Key Concepts\n"
        "Identify the core concepts, theories, methods, and techniques. For each, "
        "provide a brief definition and explain its importance.\n\n"
        "## Main Arguments & Findings\n"
        "Extract the primary claims, arguments, and findings. Note the strength "
        "of supporting evidence where discernible.\n\n"
        "## Connections to Existing Wiki\n"
        "How does this source connect to existing wiki pages? Which pages should "
        "be updated? Are there new cross-references to establish?\n\n"
        "## Contradictions & Tensions\n"
        "Does this source contradict or complicate anything already in the wiki? "
        "Flag any tensions that need resolution.\n\n"
        "## Recommendations\n"
        "List specific wiki pages that should be created or updated based on this "
        "analysis. Include proposed page titles and types.\n\n"
        "---\n\n"
        f"## Wiki Purpose\n{purpose}\n\n"
        f"## Current Wiki Index\n{index}\n\n"
        "---\n\n"
        f"## Source Document\n{source_content}\n\n"
        "---\n\n"
        "Do not output chain-of-thought, hidden reasoning, or a thinking transcript. "
        "Provide only the structured analysis above."
        + lang_rule  # 尾部重复语言指令
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
