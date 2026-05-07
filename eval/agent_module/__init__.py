from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

_ANSWERS = {
    "ResearchMate 可以做什么？": (
        "ResearchMate 是本地优先的个人科研助手，支持本地 RAG、长期记忆、"
        "外部学术检索、规划批处理任务和周报生成。"
    ),
    "如何导入 PDF 到知识库？": (
        "先把 PDF 上传到 OSS 或本地缓存，再通过 rmcli ingest 或 " "/v1/knowledge/ingest 入库。"
    ),
    "回答论文问题时需要注意什么？": (
        "必须先检索知识库，只能基于证据回答，并使用 [source: paper_id, p.N] 形式引用。"
    ),
    "如何查看我的长期记忆？": (
        "可以调用 load_memory 工具，或通过 /v1/memory 查询研究方向、偏好和近期任务。"
    ),
    "请记住我偏好先给结论，再给依据。": (
        "我会把这个写入 writing_style 长期记忆，后续写作会优先使用先结论后依据的风格。"
    ),
    "你会直接抓 Google Scholar 吗？": (
        "MVP 阶段不直接抓取 Google Scholar，优先使用 arXiv 和 Semantic Scholar。"
    ),
    "帮我找几篇 RAG 相关论文。": (
        "可以交给 Scout 调用 arXiv、Semantic Scholar 和网页抓取工具，整理候选论文列表。"
    ),
    "帮我整理这周的 5 篇论文并生成周报。": (
        "可以通过 /v1/tasks/run 或 rmcli task run weekly-report 启动异步周报任务。"
    ),
    "从历史论文里筛出最相关的 50 篇。": (
        "可以通过 filter_papers 任务执行 score_batch、prune 和 refine_query 的迭代筛选。"
    ),
    "如何备份 data 目录？": (
        "运行 scripts/backup.py 即可将 ./data/ 打包并上传到 OSS 或本地对象存储。"
    ),
    "哪个接口只检查进程是否活着？": "使用 /v1/livez，它不依赖外部资源。",
    "哪个接口检查本地依赖是否就绪？": (
        "使用 /v1/readyz，它会检查配置、Chroma、SQLite 和缓存目录。"
    ),
    "怎么查看当前服务版本？": (
        "调用 /v1/version 可以看到版本、git sha、ADK 版本、模型和运行模式。"
    ),
    "删除 session 后会发生什么？": (
        "会话删除会触发 Memory Curator，将该会话中的可归档信息写入长期记忆。"
    ),
    "知识库导入是同步还是异步？": (
        "知识库导入是异步任务，POST /v1/knowledge/ingest 会返回 job_id。"
    ),
    "如何查询论文元数据？": "使用 /v1/papers 可以按 user_id、tag、year 和 q 进行查询。",
    "如何更新论文的标签和评分？": (
        "使用 PATCH /v1/papers/{paper_id} 修改 tags、read_at 和 rating。"
    ),
    "怎么取消正在运行的任务？": "使用 POST /v1/tasks/{task_id}/cancel 即可取消任务。",
    "规划模式的输出格式是什么？": (
        "PlanReActPlanner 会使用 /*PLANNING*/、/*REASONING*/、"
        "/*ACTION*/ 和 /*FINAL_ANSWER*/ 标记。"
    ),
    "如何更新一条长期记忆？": ("使用 PATCH /v1/memory/{memory_id} 可以更新内容、分类或过期时间。"),
}


def _request_text(llm_request: LlmRequest) -> str:
    parts: list[str] = []
    for content in llm_request.contents:
        for part in content.parts or []:
            text = getattr(part, "text", None)
            if text:
                parts.append(str(text))
    return "\n".join(parts)


def _answer_for(prompt: str) -> str:
    for query, answer in _ANSWERS.items():
        if query in prompt:
            return answer
    return "ResearchMate 是本地优先的个人科研助手，支持 RAG、记忆、检索和任务执行。"


class _EvalLlm(BaseLlm):
    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        yield LlmResponse(
            model_version=self.model,
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=_answer_for(_request_text(llm_request)))],
            ),
            partial=False,
        )


root_agent = LlmAgent(
    name="researchmate",
    model=_EvalLlm(model="researchmate-eval-stub"),
    instruction="Return deterministic ResearchMate baseline answers for ADK eval.",
)

agent = SimpleNamespace(root_agent=root_agent)
