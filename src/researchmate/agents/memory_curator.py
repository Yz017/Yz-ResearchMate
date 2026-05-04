from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from researchmate.config import get_settings

_INSTRUCTION = """
你是 ResearchMate 的后台 Memory Curator。你的职责是从会话或任务摘要中抽取少量稳定事实，
并归类为 research_direction、advisor_requirements、writing_style、recent_tasks 四类之一。
只抽取用户明确表达或任务完成后确定的信息；不要保存闲聊、临时推测或论文正文事实。
输出应保持短句，便于长期检索和后续合并。
""".strip()


def build_memory_curator_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="memory_curator",
        model=LiteLlm(model=settings.researchmate_llm_model),
        instruction=_INSTRUCTION,
    )


memory_curator_agent = build_memory_curator_agent()
