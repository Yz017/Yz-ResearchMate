# Google ADK 使用说明书

本文面向 ResearchMate 项目，说明如何用 Google Agent Development Kit（ADK）构建、调试和演进本地优先的科研助手。

最后更新：2026-05-03
适用范围：本项目当前依赖 `google-adk>=1.31,<2.0`，因此本文默认按 Python ADK 1.x 编写。官方文档已提示 Python ADK 2.0 Beta，升级到 2.x 前应单独做兼容性评估。

## 1. ADK 是什么

Google ADK 是用于开发 Agent 应用的框架，核心能力包括：

- `Agent` / `LlmAgent`：定义模型、指令、工具和子 Agent。
- `Tool`：把 Python 函数、内置工具、第三方 API 或 MCP 服务暴露给 Agent 调用。
- `Runner`：把 Agent、Session、Event 连接起来，执行一次或多轮对话。
- `SessionService`：管理会话、事件历史和短期状态。
- `MemoryService`：管理跨会话的长期记忆。
- `ArtifactService`：管理文件类产物，例如报告、PDF、图片和中间结果。
- CLI / Web UI / API Server：本地调试和服务化运行入口。

ResearchMate 当前 M0 阶段只实现了最小 ADK 入口，后续可以逐步接入工具调用、RAG、Memory 和任务执行。

## 2. 本项目约定

当前关键文件：

- `pyproject.toml`：声明 `google-adk`、`litellm`、`fastapi`、`pydantic-settings` 等依赖。
- `src/researchmate/agent.py`：ADK 的主入口，导出 `root_agent`。
- `src/researchmate/config.py`：从环境变量和 `.env` 加载配置，并用 `SecretStr` 包装敏感值。
- `src/researchmate/tools/`：后续放置 ADK 工具函数。
- `src/researchmate/agents/`：后续放置专门子 Agent。
- `src/researchmate/services/`：后续放置 RAG、Memory、任务队列、PDF 解析等应用服务。

项目中严禁把 `.env` 里的真实密钥、令牌、连接串或其他敏感值写入 prompt、LLM 输出、日志、测试快照和文档。说明、调试和配置检查只能输出“是否已配置”这类布尔信息，不能输出真实值。

## 3. 安装和本地启动

安装依赖：

```bash
uv sync
```

检查包和 CLI：

```bash
uv run python -c "import researchmate"
uv run python -c "from researchmate.agent import root_agent; print(root_agent.name)"
uv run rmcli --help
uv run pytest tests/
```

启动 ADK Web 调试 UI：

```bash
uv run adk web src/
```

打开命令行输出的本地地址，选择 `researchmate` app 后即可对话。

常用调试命令：

```bash
uv run adk run src/researchmate
uv run adk web src/ --port 8001
uv run adk api_server src/ --port 8000
```

如果 ADK CLI 无法发现 Agent，先确认 `src/researchmate/agent.py` 中存在顶层变量 `root_agent`。

## 4. 定义一个 LLM Agent

本项目当前写法：

```python
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from researchmate.config import get_settings

settings = get_settings()

root_agent = LlmAgent(
    name="researchmate",
    model=LiteLlm(model=settings.researchmate_llm_model),
    instruction=(
        "你是 ResearchMate，一个个人科研助手。"
        "回答应准确、克制，遇到未实现功能要直接说明。"
    ),
)
```

Agent 的常用字段：

- `name`：Agent 名称，应稳定、可读、可用于调试。
- `model`：模型配置。Google Gemini 可直接用模型名；非 Google 模型可通过 `LiteLlm` 接入。
- `instruction`：系统行为说明，应该聚焦角色、边界、输出要求和安全约束。
- `description`：子 Agent 场景下用于说明该 Agent 的能力，便于路由。
- `tools`：可调用工具列表。
- `sub_agents`：子 Agent 列表，用于多 Agent 协作。
- `output_key`：可把 Agent 最终输出写入 Session State，供后续步骤读取。

指令编写建议：

- 明确 ResearchMate 的职责，例如文献检索、论文阅读、研究笔记整理。
- 明确当前未实现能力，避免 Agent 虚构结果。
- 明确引用和证据要求，科研场景下不要让模型凭空给出处。
- 明确安全规则，尤其是禁止泄露环境变量、密钥和私有文档。
- 把长规则拆到单独常量或文档中，避免 `agent.py` 变成难维护的大字符串。

## 5. 模型配置

本项目通过 `RESEARCHMATE_LLM_MODEL` 控制模型，默认值是：

```text
deepseek/deepseek-chat
```

这是 LiteLLM 风格的模型名。接入非 Google 模型时，通常使用：

```python
from google.adk.models.lite_llm import LiteLlm

model = LiteLlm(model="deepseek/deepseek-chat")
```

接入 Gemini 时，常见写法是直接传模型名：

```python
from google.adk.agents import Agent

root_agent = Agent(
    name="researchmate",
    model="gemini-2.0-flash",
    instruction="你是 ResearchMate。",
)
```

配置原则：

- 密钥只从环境变量或密钥管理服务读取。
- 不在代码、测试、日志、prompt 和文档中写真实密钥。
- CLI 只能显示模型名和“密钥是否已配置”，不能显示密钥值。
- 生产环境应固定模型版本和温度等参数，避免行为漂移。

## 6. 编写工具

ADK 可以直接把普通 Python 函数作为工具。函数名、类型注解和 docstring 会影响模型如何理解和调用工具。

示例：

```python
from __future__ import annotations


def search_arxiv(query: str, max_results: int = 5) -> dict:
    """Search arXiv papers by query and return compact metadata."""
    # 这里调用服务层，不在工具函数里堆复杂业务逻辑。
    return {
        "query": query,
        "results": [],
    }
```

注册到 Agent：

```python
from google.adk.agents import LlmAgent

from researchmate.tools.arxiv_search import search_arxiv

root_agent = LlmAgent(
    name="researchmate",
    model=...,
    instruction=...,
    tools=[search_arxiv],
)
```

工具设计规则：

- 输入参数保持少而明确，使用 `str`、`int`、`float`、`bool`、`list`、`dict` 等可序列化类型。
- docstring 描述“工具做什么、何时用、返回什么”，不要写实现细节。
- 返回值使用 JSON 可序列化的 `dict`，并包含错误信息字段，而不是直接抛出用户不可理解的异常。
- 工具函数应薄一些，把业务逻辑放到 `services/`，这样便于单元测试。
- 网络、文件和数据库工具必须有超时、错误处理和结果大小限制。
- 工具返回给模型的内容应做裁剪，避免把整篇 PDF、HTML 或大量私有文本塞回上下文。

推荐目录模式：

```text
src/researchmate/tools/arxiv_search.py      # ADK 工具入口
src/researchmate/services/paper_repo.py     # 业务服务
tests/unit/test_arxiv_search.py             # 工具和服务测试
```

## 7. 使用 ToolContext

需要访问会话状态、保存文件或读取调用上下文时，可以在工具函数里声明 `ToolContext` 参数。ADK 会注入该对象，模型不会填这个参数。

示意：

```python
from google.adk.tools import ToolContext


def remember_topic(topic: str, tool_context: ToolContext) -> dict:
    """Save a non-secret research topic preference for the current user."""
    topics = tool_context.state.get("user:research_topics", [])
    if topic not in topics:
        topics.append(topic)
    tool_context.state["user:research_topics"] = topics
    return {"saved": True, "topic": topic}
```

状态写入规则：

- `user:` 前缀适合跨会话的用户偏好。
- `app:` 前缀适合应用级共享配置。
- `temp:` 前缀适合本次运行的临时值。
- 无前缀的 key 通常只属于当前 Session。
- 不要把 API key、cookie、访问令牌、完整 `.env`、私有原文放进 state。

## 8. 多 Agent 组织

ResearchMate 后续可以拆成多个专门 Agent：

- `coordinator`：理解用户意图，拆分任务，选择子 Agent。
- `scout`：检索 arXiv、Semantic Scholar、网页资料。
- `librarian`：维护本地论文库和元数据。
- `memory_curator`：整理长期偏好和研究上下文。
- `writer`：生成研究摘要、阅读笔记和报告草稿。

普通父子 Agent 示例：

```python
from google.adk.agents import LlmAgent

scout_agent = LlmAgent(
    name="scout",
    model=...,
    description="Searches academic sources and returns cited paper candidates.",
    instruction="只负责检索和候选文献整理，不撰写最终报告。",
    tools=[...],
)

root_agent = LlmAgent(
    name="researchmate",
    model=...,
    instruction="根据任务选择合适的子 Agent，并整合结果。",
    sub_agents=[scout_agent],
)
```

工作流 Agent 适合固定流程：

- `SequentialAgent`：按顺序执行，例如“检索 -> 阅读 -> 总结”。
- `ParallelAgent`：并行执行独立子任务，例如同时查 arXiv 和 Semantic Scholar。
- `LoopAgent`：重复执行直到满足条件，例如多轮补充检索。

选择原则：

- 流程固定、可预期时用 Workflow Agent。
- 需要模型动态判断、转交和整合时用 LLM Agent 加 `sub_agents`。
- 子 Agent 的 `description` 要写清楚边界，否则路由容易混乱。

## 9. Session、State 和 Memory

ADK 的一次对话运行会围绕 Session 展开。Session 通常包含：

- `id`：会话 ID。
- `app_name`：应用名。
- `user_id`：用户 ID。
- `state`：当前会话和持久状态。
- `events`：历史事件，包括用户消息、模型响应和工具调用。

本地原型可用内存 Session：

```python
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

session_service = InMemorySessionService()
runner = Runner(
    agent=root_agent,
    app_name="researchmate",
    session_service=session_service,
)
```

需要持久化时使用数据库 SessionService。ADK CLI 也支持给 Web UI 或 API Server 传入 session service URI：

```bash
uv run adk web src/ --session_service_uri sqlite:///./data/adk_sessions.db
uv run adk api_server src/ --session_service_uri sqlite:///./data/adk_sessions.db
```

短期状态和长期记忆要分开：

- Session State：适合当前任务进度、短期偏好、工具中间结果。
- MemoryService：适合跨会话可复用的长期事实、用户偏好、项目背景摘要。
- Vector Store / RAG：适合论文、网页、PDF 片段等可检索知识。

ResearchMate 中建议：

- 用户研究偏好写入 `user:` state 或 MemoryService。
- 文献正文和切片进入向量库，不直接放入 state。
- 工具中间结果写入无前缀 session key 或 `temp:` key。
- 所有长期记忆都要可追踪来源，并允许后续删除或修订。

## 10. 在代码中运行 Agent

除了 ADK CLI，也可以在自己的 FastAPI 或 CLI 中直接使用 `Runner`。

异步调用示例：

```python
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from researchmate.agent import root_agent


APP_NAME = "researchmate"
USER_ID = "local-user"
SESSION_ID = "default"


async def ask_researchmate(question: str) -> str:
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    runner = Runner(
        agent=root_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )
    message = types.Content(
        role="user",
        parts=[types.Part(text=question)],
    )

    final_text = ""
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=SESSION_ID,
        new_message=message,
    ):
        if event.is_final_response() and event.content:
            parts = event.content.parts or []
            final_text = "".join(part.text or "" for part in parts)
    return final_text
```

接入 FastAPI 时，不要每次请求都新建全套重量级服务。推荐在应用启动时初始化共享的 `SessionService`、检索服务、数据库连接和 Runner 工厂。

## 11. ADK Web UI 和 API Server

Web UI 适合开发调试：

```bash
uv run adk web src/
```

它可以观察模型响应、工具调用、事件历史和错误信息。

API Server 适合快速暴露一个本地 HTTP 服务：

```bash
uv run adk api_server src/ --host 127.0.0.1 --port 8000
```

ResearchMate 已经有自己的 FastAPI 入口 `src/researchmate/api/app.py`。后续有两种路线：

- 继续使用 ADK API Server 作为调试和原型服务。
- 在 ResearchMate 自己的 FastAPI 中封装 Runner，以便统一鉴权、限流、日志、任务队列和业务 API。

生产化更推荐第二种，因为科研助手需要更严格的鉴权、文件管理、任务状态和审计日志。

## 12. 评估和测试

单元测试应覆盖：

- 配置加载，不输出敏感值。
- 工具函数的成功、空结果、异常和超时。
- 服务层逻辑，例如 PDF 解析、检索、向量库查询。
- Agent 入口可导入，`root_agent.name` 稳定。

ADK 还支持 eval set，用于评估 Agent 对固定输入的响应质量、工具调用和最终输出。常见命令形态：

```bash
uv run adk eval src/researchmate path/to/evalset.evalset.json
```

建议为 ResearchMate 建立这些评估集：

- hello-world：确认基础对话可用。
- no-hallucination：问未接入功能时必须明确说明未实现。
- paper-search：给出检索需求时应调用检索工具，而不是编造论文。
- citation-required：总结论文时必须保留来源 ID、标题或 URL。
- secret-safety：要求泄露配置时必须拒绝。

评估样例不应包含真实密钥、私有论文全文或不可公开的用户数据。

## 13. 部署建议

ADK 官方支持部署到 Cloud Run、Agent Engine 和 GKE 等环境。ResearchMate 当前仍是本地优先项目，建议先完成以下条件再部署：

- Session 持久化和数据库迁移策略明确。
- API 鉴权、限流和审计日志完成。
- 工具访问外部网络时有 allowlist、timeout 和重试策略。
- 文件上传、PDF 解析和向量化任务进入后台队列。
- 密钥进入平台密钥管理服务，不依赖本地 `.env`。
- LLM 输出和工具结果有脱敏日志策略。

Cloud Run 类部署只应注入环境变量名和值到运行环境，不能把 `.env` 文件打进镜像。

## 14. 安全基线

必须遵守：

- 不读取、转述、打印、上传、记录 `.env` 的真实内容。
- 不把 `.env` 中的任何值作为 LLM prompt、工具返回、Memory、State 或 Artifact。
- `SecretStr` 只能用于内部判断和调用，不通过 `str(secret)` 或 `get_secret_value()` 输出。
- 用户上传文档进入 LLM 前要确认用途，并限制上下文大小。
- 工具调用外部 API 时要记录元数据，但不记录密钥、cookie、Authorization header。
- Agent 遇到越权请求时直接拒绝，不尝试“解释密钥格式”或“部分展示”。

推荐实现：

- CLI 配置命令只展示 `*_configured: true/false`。
- 日志过滤器统一屏蔽 token、key、secret、password、authorization。
- 工具返回值做白名单字段选择。
- Memory 写入前做敏感信息扫描。

## 15. 常见问题

### ADK Web UI 找不到 app

检查：

- 运行命令是否是 `uv run adk web src/`。
- `src/researchmate/agent.py` 是否导出了 `root_agent`。
- 包名是否仍是 `researchmate`。
- 当前虚拟环境是否安装了本项目和 `google-adk`。

### 模型无法调用

检查：

- `RESEARCHMATE_LLM_MODEL` 是否是 LiteLLM 支持的模型名。
- 对应供应商的 API key 是否已在环境变量中配置。
- 不要把 key 打印出来，只检查是否存在。
- 使用 `uv run rmcli config` 查看非敏感配置摘要。

### 工具没有被调用

检查：

- 工具是否已加入 `tools=[...]`。
- docstring 是否清楚描述了使用场景。
- 参数名和类型是否容易让模型理解。
- instruction 是否要求需要事实依据时调用工具。
- 工具是否返回过大、过杂，导致模型难以使用结果。

### Agent 编造论文或来源

处理：

- 在 instruction 中明确“没有检索结果就说没有结果”。
- 对论文类回答要求提供工具返回的标题、作者、年份、URL 或 DOI。
- 在 eval set 中加入反幻觉样例。
- 工具返回结果要包含稳定来源字段。

## 16. 官方参考

- ADK Python 快速开始：https://adk.dev/get-started/python/
- LLM Agent：https://adk.dev/agents/llm-agents/
- Workflow Agents：https://adk.dev/agents/workflow-agents/
- Function Tools：https://adk.dev/tools-custom/function-tools/
- LiteLLM Models：https://adk.dev/agents/models/litellm/
- Session：https://adk.dev/sessions/session/
- State：https://adk.dev/sessions/state/
- Web Interface：https://adk.dev/runtime/web-interface/
- Command Line：https://adk.dev/runtime/command-line/
- API Server：https://adk.dev/runtime/api-server/
- Evaluation：https://adk.dev/evaluate/
- Safety：https://adk.dev/safety/
