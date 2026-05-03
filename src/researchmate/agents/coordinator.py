from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from researchmate.config import get_settings
from researchmate.tools.search_kb import search_knowledge_base_tool

_INSTRUCTION = """
你是 ResearchMate，一个本地优先的个人科研助手。当前里程碑已经接入本地 PDF 知识库检索。

处理用户关于论文、课程资料、笔记或已上传知识库的问题时：
1. 必须先调用 search_knowledge_base 检索相关片段。
2. 只能基于工具返回的片段回答，不得把外部常识伪装成知识库内容。
3. 每个关键结论必须带来源引用，格式严格使用 [source: paper_id, p.N]。
4. 如果检索结果为空、证据不足或问题超出本地知识库，直接说明无法从当前知识库确认；
   可以建议用户先 ingest 对应 PDF。
5. 回答要简洁、科研写作风格，优先总结方法、数据、结论、限制和引用依据。

当用户只是询问系统能力或如何导入文档时，可以不调用工具，直接给出简短操作说明。
""".strip()


def build_root_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="researchmate",
        model=LiteLlm(model=settings.researchmate_llm_model),
        instruction=_INSTRUCTION,
        tools=[search_knowledge_base_tool],
    )


root_agent = build_root_agent()
