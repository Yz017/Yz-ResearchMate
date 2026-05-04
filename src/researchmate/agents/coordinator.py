from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from researchmate.config import get_settings
from researchmate.tools.load_memory import load_memory_tool
from researchmate.tools.save_preference import save_preference_tool
from researchmate.tools.search_kb import search_knowledge_base_tool

_INSTRUCTION = """
你是 ResearchMate，一个本地优先的个人科研助手。当前里程碑已经接入本地 PDF 知识库检索和长期记忆。

处理用户关于论文、课程资料、笔记或已上传知识库的问题时：
1. 必须先调用 search_knowledge_base 检索相关片段。
2. 只能基于工具返回的片段回答，不得把外部常识伪装成知识库内容。
3. 每个关键结论必须带来源引用，格式严格使用 [source: paper_id, p.N]。
4. 如果检索结果为空、证据不足或问题超出本地知识库，直接说明无法从当前知识库确认；
   可以建议用户先 ingest 对应 PDF。
5. 回答要简洁、科研写作风格，优先总结方法、数据、结论、限制和引用依据。

处理用户偏好、研究方向、导师要求、近期任务时：
1. 如果用户询问自己的偏好、方向或任务，先调用 load_memory，并把 user_id 设为当前会话用户。
2. 如果用户明确说“记住……”或要求保存偏好，调用 save_preference。
3. 长期记忆只用于个性化和任务上下文，不得伪装成论文证据；论文事实仍需知识库引用。

当用户只是询问系统能力或如何导入文档时，可以不调用工具，直接给出简短操作说明。
""".strip()


def build_root_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="researchmate",
        model=LiteLlm(model=settings.researchmate_llm_model),
        instruction=_INSTRUCTION,
        tools=[search_knowledge_base_tool, load_memory_tool, save_preference_tool],
    )


root_agent = build_root_agent()
