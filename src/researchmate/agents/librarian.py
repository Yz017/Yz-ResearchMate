from __future__ import annotations

from google.adk.agents import LlmAgent

from researchmate.agents.llm_policy import (
    after_model_callback,
    before_model_callback,
    build_agent_llm,
    on_model_error_callback,
)
from researchmate.config import get_settings
from researchmate.tools.search_kb import search_knowledge_base_tool

_INSTRUCTION = """
你是 ResearchMate 的 Librarian，专门处理本地知识库中的论文、笔记和课程资料。

规则：
1. 回答任何论文事实前必须调用 search_knowledge_base。
2. 只能基于检索片段回答，不得用外部常识补齐缺失事实。
3. 每个关键结论必须带 [source: paper_id, p.N] 引用。
4. 检索证据不足时，明确说明当前知识库无法确认。
""".strip()


def build_librarian_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="librarian",
        description="Local RAG specialist for citation-grounded literature and note QA.",
        model=build_agent_llm(settings),
        instruction=_INSTRUCTION,
        before_model_callback=before_model_callback,
        after_model_callback=after_model_callback,
        on_model_error_callback=on_model_error_callback,
        tools=[search_knowledge_base_tool],
    )
