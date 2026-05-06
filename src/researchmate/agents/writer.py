from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from researchmate.config import get_settings
from researchmate.tools.load_memory import load_memory_tool

_INSTRUCTION = """
你是 ResearchMate 的 Writer，负责把已检索和已验证的信息写成 Markdown 产物。

规则：
1. 写作前先按需调用 load_memory 获取用户写作偏好。
2. 论文事实和引用必须来自上游提供的本地知识库证据或外部检索元数据。
3. 本地知识库事实引用使用 [source: paper_id, p.N]，外部元数据必须标明来源。
4. 输出结构清晰、简洁，避免无证据的夸大结论。
""".strip()


def build_writer_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="writer",
        description="Markdown writing specialist for reports, summaries, and research notes.",
        model=LiteLlm(model=settings.researchmate_llm_model),
        instruction=_INSTRUCTION,
        tools=[load_memory_tool],
    )
