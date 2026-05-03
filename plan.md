# ResearchMate · 实施计划

> 配套文档：[`research.md`](./research.md)（设计依据）、[`demands.txt`](./demands.txt)（原始需求）
>
> **核心原则**：
> 1. 每个里程碑结束都能 **脱离 Java 单独验收**（`adk web` / `rmcli` / `smoke_test.py`），项目本身即可交付。
> 2. 每条步骤完成后在前面方括号里打钩 `[x]`；未完成保持 `[ ]`。
> 3. 严格按 M0 → M7 顺序推进；同一 M 内的子任务尽量按编号顺序，相互依赖明显的不要跳跃。
> 4. 计划写完不等于设计冻结：开发中遇到与 `research.md` 冲突时，先更新 `research.md`，再回头改 `plan.md`。在更新`research.md`之前必须获得开发者许可。

**进度概览（手动维护）**

| 里程碑 | 主题                                    | 状态 | 完成日期 |
| ------ | --------------------------------------- | ---- | -------- |
| M0     | 项目初始化与脚手架                      | ✅    | 2026-05-02 |
| M1     | RAG + 对话骨架                          | ☐    |          |
| M2     | FastAPI 服务化 + CLI 雏形               | ☐    |          |
| M3     | Memory + 知识库 API                     | ☐    |          |
| M4     | 工具调用 + 多 Agent + 周报任务（🎯 MVP） | ☐    |          |
| M5     | 规划、批处理、稳定化                    | ☐    |          |
| M6     | Java Spring Boot 联调                   | ☐    |          |
| M7     | 运维与长期化（可选）                    | ☐    |          |

---

## M0 · 项目初始化与脚手架

> **出口**：`uv sync` 通过，`uv run python -c "import researchmate"` 不报错；DeepSeek API key 联通；运行模式（GPU / CPU）已检测并记录（CPU 模式不阻塞后续里程碑）。
>
> **预期工时**：1–2 天

### 0.1 仓库与目录

- [x] 初始化 git 仓库（`git init`），主分支 `main`
- [x] 创建 `.gitignore`：覆盖 `.env`、`data/`、`logs/`、`__pycache__/`、`.venv/`、`*.egg-info`、`*.pyc`；**注意 `uv.lock` 与 `pyproject.toml` 必须入仓**，不在忽略列表
- [x] 按下方目录规范创建空骨架（每个 Python 包目录放 `__init__.py` 占位）

#### 目录结构与用途说明

下面是项目最终形态的完整目录树。`*` 标记的目录在 M0 阶段先建空骨架；其他文件随后续里程碑逐步产出。

```
ResearchAssistant/
├── src/researchmate/             # * 主包，uv/pip install -e 后可 `import researchmate`
│   ├── __init__.py
│   ├── agent.py                  # * ADK 入口：导出 root_agent，供 `adk web src/` 自动发现（M0 占位 / M1 接入真实 Coordinator）
│   ├── config.py                 # Pydantic Settings：统一从 .env 读配置（M0）
│   ├── agents/                   # * 各 LlmAgent / WorkflowAgent 实现模块
│   │   ├── coordinator.py        #   顶层调度 agent，挂 PlanReActPlanner（M1 起）
│   │   ├── librarian.py          #   RAG 专用子 agent（M4）
│   │   ├── scout.py              #   外部检索子 agent，调 arXiv/S2/网页（M4）
│   │   ├── writer.py             #   写作子 agent，按用户偏好生成产物（M4）
│   │   └── memory_curator.py     #   会话结束后做记忆抽取与归档（M3）
│   ├── api/                      # * FastAPI 应用层，对外 HTTP/SSE 入口
│   │   ├── __init__.py           #   `from .app import app`，让 `uvicorn researchmate.api:app` 可定位
│   │   ├── app.py                #   调 get_fast_api_app() 装配主 app（M2）
│   │   ├── routes/               #   业务路由：chat / knowledge / memory / papers / tasks
│   │   ├── middleware/           #   auth_middleware / trace_id / 全局错误处理
│   │   └── schemas.py            #   Pydantic 请求/响应模型（与 OpenAPI 对应）
│   ├── cli/                      # * rmcli 命令行客户端（独立模式 UI）
│   │   ├── main.py               #   Typer 入口，注册子命令组
│   │   └── commands/             #   health / chat / ingest / memory / task / papers 等子命令
│   ├── services/                 # * 业务服务层（不依赖 ADK / FastAPI，便于单测）
│   │   ├── vector_store.py       #   Chroma client 封装（kb_chunks + memory_records）
│   │   ├── pdf_parser.py         #   PDF 文本抽取与按段落切分
│   │   ├── retriever.py          #   dense + sparse + RRF + rerank 混合检索
│   │   ├── memory_service.py     #   长期 Memory（继承 BaseMemoryService）
│   │   ├── oss_client.py         #   阿里云 OSS SDK 封装（put/get/sign_url）
│   │   ├── paper_repo.py         #   papers.db 元数据 CRUD
│   │   └── job_runner.py         #   异步任务运行器（jobs.db）
│   └── tools/                    # * 暴露给 Agent 调用的 FunctionTool / MCP wrapper
│       ├── search_kb.py          #   知识库检索（M1）
│       ├── arxiv_search.py       #   arXiv MCP 包装（M4）
│       ├── s2_search.py          #   Semantic Scholar API（M4）
│       ├── web_fetch.py          #   网页正文抽取，含 prompt-injection 防护（M4）
│       ├── load_memory.py        #   Agent 读取长期记忆（M3）
│       └── save_preference.py    #   显式写入用户偏好（M3）
├── scripts/                      # * 运维 / 一次性脚本（不进 src，不被打包）
│   ├── ingest.py                 #   批量 ingest 本地 PDF 的开发便捷脚本（M1）
│   ├── smoke_test.py             #   端到端冒烟测试，每个里程碑必跑（M2 起）
│   └── backup.py                 #   ./data/ → OSS 数据备份（M5）
├── tests/                        # * pytest 测试目录
│   ├── unit/                     #   单元测试，无需启动服务或外部依赖
│   └── integration/              #   集成测试，需要服务起来或外部 API
├── examples/                     # * 用户与开发参考样例
│   ├── curl/                     #   每个端点的 curl 调用示例（接口契约最低保障文档）
│   └── pdfs/                     #   仓库自带示例 PDF（CC-BY，用于 README quick-start）
├── docs/                         # * 项目文档
│   ├── openapi.json              #   FastAPI 自动导出的 API schema（M2 起每次接口变更同步）
│   ├── task_kinds.md             #   任务 kind 与 params 完整 schema（M4）
│   ├── architecture.md           #   面向新人的精简架构（research.md 子集）
│   ├── perf_baseline.md          #   性能基线（M1 GPU、M6 联调压测）
│   ├── eval_baseline.md          #   adk eval 回归基线（M5）
│   ├── demos/                    #   每个里程碑的演示视频与说明
│   └── templates/                #   周报等 Markdown 模板（M4）
├── data/                         #   运行时数据，全部 git 忽略（M0 不必预创建）
│   ├── chroma/                   #   Chroma 向量库本地文件（含 kb_chunks + memory_records 两个 collection）
│   ├── cache/                    #   OSS 文件本地缓存
│   ├── sessions.db               #   ADK DatabaseSessionService 存储
│   ├── papers.db                 #   论文元数据
│   └── jobs.db                   #   异步任务状态表
├── logs/                         #   loguru JSON 日志（git 忽略）
├── .env.example                  #   配置模板，可入仓
├── .env                          #   实际配置（git 忽略，保护密钥）
├── .gitignore
├── pyproject.toml                #   项目元数据 + 依赖 + 工具配置（ruff/black/mypy/pytest）
├── uv.lock                       #   uv 锁定文件，保证可复现，**入仓**
├── README.md                     #   quick-start + 安装 + 运行
├── CHANGELOG.md
├── research.md                   #   设计文档（已存在）
├── plan.md                       #   本文件（已存在）
└── demands.txt                   #   原始需求（已存在）
```

> 设计要点：
> - **`src/` layout**：避免 import 路径污染，强制走包安装路径，单测时不会误 import 到根目录脚本。
> - **`src/researchmate/agent.py` 是 ADK 约定的入口文件**：必须导出名为 `root_agent` 的 Agent 对象。`adk web src/` 会扫 `src/` 下每个直接子包寻找 `agent.py`，把每个找到的当作一个 app；本项目这样 `researchmate` 就是唯一的 app 名。`agents/`（复数）是内部实现模块，与 `agent.py`（单数，入口）不冲突。
> - **`api/__init__.py` 必须 re-export `app`**：`uvicorn researchmate.api:app` 才能定位到 FastAPI 实例，否则只会找到 `api` 包而非 `app` 对象。
> - **services/ 与 tools/ 分层**：`services/` 是纯业务逻辑（容易单测），`tools/` 只是把 services 包装成 Agent 可调用的 FunctionTool。这样 Agent 层可以替换而服务层不动。
> - **scripts/ 与 src/ 分离**：脚本不打包，避免在生产 import 时误执行；CI 也只跑 `src/` 与 `tests/`。
> - **data/ 与 logs/ 全部 gitignore**：所有运行态数据都在这里，删掉重建即可，不污染版本历史。

### 0.2 Python 环境与包管理

**选型决定**：**Python 3.11+** + **[uv](https://github.com/astral-sh/uv)**（Astral 出品的现代 Python 包管理器）。

**为什么是 uv（不选 pip + venv / poetry / conda）**：
- 比 pip 快 10–100×：PyTorch、chromadb、FlagEmbedding 这类大依赖明显省时间
- 原生支持 PEP 621 的 `pyproject.toml`，无需 poetry 这层间接
- 自动管理 venv 与 Python 版本（不需要单独装 pyenv / virtualenv）
- 锁定文件 `uv.lock` 保证不同机器 / CI 上完全可复现
- 单一 Rust 二进制，零 Python 启动时间，跨平台一致
- 与 pip 命令兼容：`uv pip install` 是 pip 的直接替代，迁移成本几乎为零

**回退方案**：若已深度依赖 conda（譬如靠 conda-forge 管 CUDA toolkit），可改为 conda 创建环境 + `uv pip install` 装包；项目本身不绑死 uv，`pyproject.toml` 是标准格式，poetry / pip 也能消费。

**依赖分层策略**：所有依赖统一在 `pyproject.toml` 的 `[project.dependencies]` 与 `[project.optional-dependencies]` 中声明，**不再单独维护 `requirements.txt`**——`uv.lock` 已是真理之源。

#### 任务清单

- [x] 安装 uv：Windows 推荐 `winget install astral-sh.uv`，或 `pip install uv`、`curl -LsSf https://astral.sh/uv/install.sh | sh`
- [x] 写 `pyproject.toml`，包含以下段：
  - [x] `[project]`：`name = "researchmate"`、`version = "0.1.0"`、`requires-python = ">=3.11"`
  - [x] `[project.dependencies]`：主依赖（按 research.md §8 五组逐项落；**注意必须包含 `aiosqlite`** —— ADK Session 走 SQLAlchemy async 驱动，没它会启动失败）
  - [x] `[dependency-groups].dev`（PEP 735 标准）：pytest、pytest-asyncio、ruff、black、mypy、httpx；`uv sync` 默认会装这一组
  - [x] `[project.scripts]`：`rmcli = "researchmate.cli.main:app"`
  - [x] `[tool.ruff]` / `[tool.black]` / `[tool.mypy]` / `[tool.pytest.ini_options]` 工具配置（M0.4 详细化）
  - [x] `[tool.hatch.build.targets.wheel].packages = ["src/researchmate"]`（或用 `setuptools` 后端，二选一）
- [x] 创建虚拟环境：`uv venv`（默认在 `./.venv`，自动选 ≥3.11 的 Python）
- [x] 同步依赖：`uv sync`（默认装主依赖 + dev 组，生成 `uv.lock`）
- [x] 激活：Windows PowerShell `.\.venv\Scripts\Activate.ps1`，或全程用 `uv run <cmd>` 不显式激活
- [x] 验证：`uv run python -c "import researchmate"` 不报错；`uv run rmcli --help` 看到 Typer 帮助
- [x] 把 `uv.lock` 入仓（保证团队 / CI 完全可复现的关键文件）

> 日常开发常用命令速查：
> - 加主依赖：`uv add <pkg>`（自动写 `[project.dependencies]` + 更新 lock）
> - 加 dev 依赖：`uv add --dev <pkg>`（写 `[dependency-groups].dev`，与本项目选型一致）
> - 升级单包：`uv lock --upgrade-package <pkg>`
> - 跑命令：`uv run pytest`、`uv run uvicorn researchmate.api:app`、`uv run adk web src/`

### 0.3 配置与密钥
- [x] 写 `.env.example`，至少含：
  - [x] `DEEPSEEK_API_KEY`
  - [x] `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` / `OSS_BUCKET` / `OSS_ENDPOINT`
  - [x] `RESEARCH_AGENT_TOKEN`（≥ 32 字符随机）
  - [x] `RESEARCH_AGENT_BIND=127.0.0.1:8000`
  - [x] `ADK_SESSION_DB_URL=sqlite+aiosqlite:///./data/sessions.db`（SQLAlchemy URL，**不是文件路径**）
  - [x] `EMBEDDING_DEVICE=auto`（`auto` / `cuda` / `cpu`）
- [x] 本地复制 `.env.example` → `.env` 并填值（已生成随机 `RESEARCH_AGENT_TOKEN`；`DEEPSEEK_API_KEY` 已在本地 `.env` 填写，密钥值不记录）
- [x] 配置 `python-dotenv` 自动加载
- [x] 写 `src/researchmate/config.py`（Pydantic Settings，字段名与上面 env 一一对应）

### 0.4 代码规范与 CI
- [x] 配置 ruff + black（`pyproject.toml` 中）
- [x] 配置 mypy 严格模式（核心模块）
- [x] pre-commit hook（ruff、black、trailing whitespace）
- [x] GitHub Actions（或本地 `make ci`）：跑 ruff + mypy + pytest
- [x] 写 README 骨架（quick-start 占位、安装步骤、目录说明）

### 0.5 ADK 入口、LLM 联通、运行模式探测
- [x] 安装 `google-adk` + `litellm`
- [x] 写最小 `src/researchmate/agent.py`：导出 `root_agent = Agent(name="researchmate", model=LiteLlm("deepseek/deepseek-chat"), instruction="你是 ResearchMate……")`；M1 再替换为真实 Coordinator
- [x] 写 `src/researchmate/__init__.py` 留空（不要在此 import agent，避免触发模型加载）
- [x] LiteLlm wrapper 调通 DeepSeek-V3：通过 ADK Runner 发送 `hello`，确认收到文本响应（未打印模型正文）
- [x] **从项目根**运行 `uv run adk web src/` 能启动；`AgentLoader("src").list_agents()` 能发现 `researchmate` 这个 app；hello-world 对话链路已由 ADK Runner 自动验收
- [x] **检测并记录运行模式**：写 `scripts/detect_runtime.py` 输出 `torch.cuda.is_available()` 与设备名，结果落 `docs/perf_baseline.md`；GPU 不可用时本项目仍可运行（M1 走 CPU 降级），不阻塞后续里程碑

### 0.6 验收
- [x] `uv sync` 一键搞定环境 + 主依赖 + dev 组
- [x] `uv run pytest tests/` 全绿（即便只有占位 test）
- [x] `uv run rmcli --help` 看到 CLI 帮助（即便子命令尚未实现）
- [x] `uv run adk web src/` 启动通过；`researchmate` app 发现通过；hello-world 对话链路已由 ADK Runner 验证
- [x] README 写明：克隆 → `winget install astral-sh.uv` → `uv sync` → 配 `.env` → `uv run adk web src/` 跑 hello-world 的 5 步
- [x] 提交 M0 完成 commit

---

## M1 · RAG + 对话骨架

> **出口**：在 `adk web` 上能就一篇本地 PDF 进行问答，回答带 `[source: paper_X, p.12]` 引用，引用准确。
>
> **预期工时**：1.5–2 周
> **独立验收**：录屏一段 `adk web` 上的问答演示，归档至 `docs/demos/M1.md` + `docs/demos/M1.mp4`

### 1.1 Embedding & Rerank（GPU 优先 / CPU 可降级）
- [x] 安装 PyTorch（有 NVIDIA GPU → CUDA 版；无 GPU → CPU 版即可，本期仍可继续）
- [x] 安装 `FlagEmbedding` 或 `sentence-transformers`
- [ ] 首次拉取 bge-m3（当前环境网络不可达，已降级为离线优先的本地 hashing fallback）
- [ ] 首次拉取 bge-reranker-v2-m3（当前环境网络不可达，已降级为 lexical fallback）
- [x] 在 `config.py` 暴露 `EMBEDDING_DEVICE`（`auto` / `cuda` / `cpu`），`auto` 时按 `torch.cuda.is_available()` 判断
- [x] 写 sanity-check 脚本：5 条句子的 embedding 余弦距离合理；rerank 分数排序合理
- [x] **CPU 降级路径**：无 GPU 时 dense embedding 走 CPU（速度下降但功能完整）；rerank 可临时关掉只用 RRF top-5（在 perf_baseline.md 标注精度损失）
- [x] 实测当前模式（GPU/CPU）的显存或 RAM 占用与单 batch 速度，记录到 `docs/perf_baseline.md`

### 1.2 Chroma 向量库
- [x] 安装 `chromadb`
- [x] 写 `services/vector_store.py`：封装 Chroma client（`./data/chroma/`）
- [x] 创建 collection `kb_chunks`（dense vector + metadata）
- [x] （选做）评估 sparse 路径：当前采用 local lexical sparse + dense RRF 的混合查询

### 1.3 PDF 解析与切分
- [x] 安装 `pypdf` + `pdfplumber`
- [x] 写 `services/pdf_parser.py`：抽取文本 + 页码 + 简易 section 切分
- [x] 切分策略：512–1024 token，按段落优先、跨段不超过 1.5×
- [x] metadata 保留：`{paper_id, title, page, section, oss_key, source_path}`
- [x] 单元测试：用 1 篇 sample PDF 验证 chunk 数量、页码、长度分布

### 1.4 Ingest 流水线
- [x] 写 `scripts/ingest.py`：本地 PDF 路径 → 解析 → chunk → embed → 写 Chroma
- [x] 处理重复 ingest（按 paper_id + chunk_hash 去重）
- [x] 进度条与失败回滚（按 PDF 维度做回滚；Chroma 不提供事务，因此采用幂等 upsert + 删除回滚）
- [x] 准备 3–5 篇示例 PDF 放到 `examples/pdfs/`
- [x] 跑通 ingest，确认 Chroma 中 chunk 数量符合预期

### 1.5 检索器
- [x] 写 `services/retriever.py`：dense top-20 + sparse top-20 → RRF 融合 → rerank top-5
- [x] 验证检索质量：手工出 5 条 query，看 top-5 是否包含正确页码
- [x] 封装为 `tools/search_kb.py` 的 `FunctionTool`，签名 `search_knowledge_base(query, filters?)`

### 1.6 Coordinator Agent（单 agent 雏形）
- [x] 写 `agents/coordinator.py`：单 `LlmAgent` + DeepSeek-V3
- [x] 写 system prompt：
  - [x] 角色定位（个人科研助手）
  - [x] 强制引用：无来源则拒答
  - [x] 引用格式 `[source: paper_id, p.N]`
- [x] 注册 `search_knowledge_base` 工具
- [x] 在 `adk web` 跑通：问"这篇论文的方法部分说了什么"

### 1.7 测试与验收
- [x] 写 `tests/test_retriever.py`：固定 query 命中预期 chunk
- [x] 写 `tests/test_pdf_parser.py`：解析示例 PDF 长度断言
- [x] 手工 QA：列 5 条问题，逐条人工验证回答与引用
- [ ] 录屏 1 段 `adk web` 演示（提问 → 回答 → 点击引用回链）
- [x] 把验收材料归档至 `docs/demos/M1.md`
- [x] 提交 M1 完成 commit + tag `v0.1.0-m1`

---

## M2 · FastAPI 服务化 + CLI 雏形

> **出口**：`uvicorn researchmate.api:app` 起服务后，`rmcli health` 与 `rmcli chat` 都能跑通；smoke-test 第 1–2 项全绿。
>
> **预期工时**：1.5 周
> **独立验收**：脱离 `adk web` 后用 `rmcli chat` 完整对话；`scripts/smoke_test.py --steps 1,2` 通过。

### 2.1 FastAPI 应用骨架
- [ ] 写 `api/app.py`：调 `get_fast_api_app(agents_dir="src", session_service_uri=settings.adk_session_db_url, ...)` 装配 ADK 自带 FastAPI app，把实例命名为 `app`
- [ ] 写 `api/__init__.py`：`from .app import app`，确保 `uvicorn researchmate.api:app` 能定位到对象
- [ ] 写启动入口 `api/__main__.py`：`uvicorn researchmate.api:app --host 127.0.0.1 --port 8000 --workers 1`
- [ ] 写 `Makefile` / `tasks.ps1`：`make serve` 一键起服务
- [ ] 写 `examples/curl/quickstart.sh`

### 2.2 中间件
- [ ] `auth_middleware`：校验 `X-Internal-Token`（与 env 比对，不一致 401）
- [ ] `trace_id_middleware`：生成 UUIDv7，注入响应头 `X-Trace-Id`，绑定到 loguru contextvars
- [ ] 全局异常处理器：把异常映射成统一错误体 `{code, message, trace_id, retryable}`
- [ ] CORS：localhost 限制（开发期）

### 2.3 系统接口（健康检查分层，避免每次探活都打 DeepSeek）
- [ ] `GET /v1/livez`：本地进程是否能响应（200 = 存活），耗时 < 5ms，**不依赖任何外部资源**
- [ ] `GET /v1/readyz`：本地依赖就绪（Chroma 文件可读、配置已加载、Session DB 可连）。运行模式（GPU/CPU）只作信息回显，**CPU 模式不视为 not-ready**。耗时 < 50ms
- [ ] `GET /v1/healthz?deep=true`：深度检查，触发一次 DeepSeek 极简调用；结果 5 分钟 TTL 缓存，避免被 Java 高频探活打爆配额或被外部 LLM 抖动误判
- [ ] `GET /v1/healthz`（默认 `deep=false`）= readyz + 缓存内最近一次的 LLM 状态
- [ ] `GET /v1/version`：返回 git sha + ADK 版本 + 默认模型 ID + 运行模式
- [ ] **约定**：Java/CLI 定时探活只调 `/livez` 或 `/readyz`；`/healthz?deep=true` 仅在故障定位或运维触发（research.md §9.3.7 已同步为此结构）

### 2.4 会话接口（包装 ADK Sessions）
- [ ] 在 `pyproject.toml` 主依赖中加 `aiosqlite`（ADK Session 走 SQLAlchemy async 驱动；缺它启动会失败）
- [ ] `.env.example` 增加 `ADK_SESSION_DB_URL=sqlite+aiosqlite:///./data/sessions.db`（**SQLAlchemy URL 格式，不是普通文件路径**）
- [ ] `config.py` 暴露 `adk_session_db_url`，`get_fast_api_app(...)` 装配时透传
- [ ] 启动时自动 `mkdir -p ./data/`，否则 SQLite 创建会失败
- [ ] `POST /v1/sessions`（入 `user_id` → 出 `session_id`）
- [ ] `GET /v1/sessions/{session_id}`
- [ ] `DELETE /v1/sessions/{session_id}`（M2 不接 Memory Curator，仅删除；归档触发点见 M3.5）

### 2.5 对话接口（SSE）
- [ ] `POST /v1/chat/{session_id}` 路由
- [ ] 把 ADK `Runner.run_async()` 事件映射成 9.3.2 SSE 事件类型：
  - [ ] `thinking`
  - [ ] `tool_call`
  - [ ] `tool_result`
  - [ ] `token`
  - [ ] `final`
  - [ ] `error`
  - [ ] `citation`（M1 检索器已能产出，本期接入流式）
- [ ] 用 `StreamingResponse` 输出 `text/event-stream`
- [ ] 异常路径：超时返回 `error` 事件后 close

### 2.6 日志与可观测
- [ ] 配置 loguru → JSON 输出到 `./logs/researchmate.json`
- [ ] 关键日志字段：`trace_id`、`user_id`、`session_id`、`event`、`latency_ms`
- [ ] 日志按天滚动 + 保留 14 天

### 2.7 CLI 雏形（`rmcli`）
- [ ] 选 CLI 框架：Typer
- [ ] `cli/main.py`：注册子命令组
- [ ] `rmcli health`：默认调 `/v1/readyz`（轻量，不打 DeepSeek）；`rmcli health --deep` 调 `/v1/healthz?deep=true` 触发完整 LLM 探活
- [ ] `rmcli session create/get/delete`
- [ ] `rmcli chat`：交互式 REPL，使用 `httpx.stream()` 接 SSE，按事件类型渲染
- [ ] 错误体反序列化与友好提示（含 trace_id）

### 2.8 Smoke-test 脚手架
- [ ] 写 `scripts/smoke_test.py` 框架（CLI 参数 `--steps 1,2,3,4,5 --base-url --deep`）
- [ ] 实现 step 1：探活 —— 无 `--deep` 时调 `/livez` + `/readyz`；带 `--deep` 时再加 `/healthz?deep=true`
- [ ] 实现 step 2：session 创建 + chat + 校验 SSE 事件序列完整性

### 2.9 文档与验收
- [ ] 导出 `openapi.json` → `docs/openapi.json`
- [ ] `examples/curl/`：health.sh / session.sh / chat.sh
- [ ] README quick-start 增加"启动服务 + `rmcli chat`"段
- [ ] smoke-test 1–2 全绿
- [ ] 提交 M2 完成 commit + tag `v0.2.0-m2`

---

## M3 · Memory + 知识库 API

> **出口**：用 `rmcli ingest sample.pdf` 入库后能问答；写入研究方向后新会话能用上；smoke-test 1–4 全绿。
>
> **预期工时**：2 周
> **独立验收**：`rmcli memory add ...` → 新 session `rmcli chat` 测试模型用上偏好；ingest 端到端 OSS 链路通。

### 3.1 OSS 接入
- [ ] 安装 `oss2`，写 `services/oss_client.py`（put/get/exists/sign_url）
- [ ] 单元测试：上传 → 下载 → 校验 sha256
- [ ] 失败重试：指数退避 3 次
- [ ] 大文件分片上传（>10MB）

### 3.2 长期 Memory Service
- [ ] 设计 `memory_records` collection schema（content, category, user_id, created_at, expires_at）
- [ ] 实现 `services/memory_service.py`，继承 `BaseMemoryService`：
  - [ ] `add_session_to_memory()` 抽取关键事实（LLM 总结）后入库
  - [ ] `search_memory(query, user_id, category?)` 向量召回
  - [ ] `expire_sweep()` 定期清理过期项
- [ ] 注册为 ADK MemoryService
- [ ] `tools/load_memory.py`：包装为 FunctionTool
- [ ] `tools/save_preference.py`：显式写入工具
- [ ] 在 Coordinator 上挂 `load_memory` + `save_preference`

### 3.3 Memory CRUD 接口
- [ ] `POST /v1/memory`（含 expires_at 可选）
- [ ] `GET /v1/memory?user_id=&category=`
- [ ] `PATCH /v1/memory/{memory_id}`
- [ ] `DELETE /v1/memory/{memory_id}`
- [ ] 单测覆盖 CRUD 与 expires 行为

### 3.4 异步任务运行器（asyncio.Task registry + jobs.db 状态机）

> 这套运行器同时支撑 M3 的知识库 ingest 和 M4 的 `/v1/tasks/*`，**不要写两套**。`FastAPI BackgroundTasks` 不能取消、不能查询、无法挂 SSE 进度，只够最简的 fire-and-forget，本项目需求已超过它。

- [ ] 设计 `jobs.db` 表：`(id, kind, state, progress, error, params_json, result_json, user_id, created_at, finished_at)`
- [ ] 状态机：`queued → running → done | failed | interrupted | cancelled`
- [ ] 写 `services/job_runner.py`，维护 `dict[job_id, asyncio.Task]` registry：
  - [ ] `submit(kind, params, user_id) -> job_id`：写 db `queued` → 启动 `asyncio.create_task(...)` → registry 登记
  - [ ] `cancel(job_id)`：`task.cancel()` + 写 db `cancelled`
  - [ ] `subscribe(job_id) -> AsyncIterator[event]`：基于 `asyncio.Queue` 推送进度事件
  - [ ] 异常捕获：所有未处理异常写 db `failed` + 完整 traceback，避免静默丢失
  - [ ] 任务结束（done/failed/cancelled）从 registry 移除，但 db 保留
- [ ] **中断恢复**：服务启动时扫所有 `state=running` 的 job 标记为 `interrupted`，调用方据此提示用户重试
- [ ] `POST /v1/knowledge/ingest`：接 OSS keys → `submit("ingest", ...)` → 返回 job_id
- [ ] `GET /v1/knowledge/jobs/{job_id}`：状态 + 进度查询
- [ ] `GET /v1/knowledge/jobs/{job_id}/events`：SSE 流式进度（基于 `subscribe`）
- [ ] `GET /v1/knowledge/documents?user_id=&tag=`：分页列表
- [ ] `DELETE /v1/knowledge/documents/{doc_id}`：连带删除 chunks

### 3.5 Memory Curator（多触发点，避免依赖用户主动删 session）

用户在实际使用中很少会主动 `DELETE` 一个 session，因此不能只把归档绑在那个事件上。下列四条触发路径必须都覆盖：

- [ ] 写 `agents/memory_curator.py`（独立 LlmAgent，不对外）
- [ ] **触发 1：显式写入** —— `save_preference` 工具或 `POST /v1/memory` 同步写库（已在 3.2 / 3.3 实现，此处确认即可）
- [ ] **触发 2：会话主动结束** —— `DELETE /v1/sessions/{id}` 时调归档
- [ ] **触发 3：会话空闲归档** —— 后台周期任务（每 5 分钟）扫 sessions 表，最近 event 超过 30 分钟（可配）的会话触发归档；用 `archived_at` 字段防重复
- [ ] **触发 4：任务完成归档** —— `/v1/tasks/{id}` 进入终态时把任务摘要归档进 `recent_tasks` 类目
- [ ] 抽取 4 类信息：`research_direction` / `advisor_requirements` / `writing_style` / `recent_tasks`
- [ ] 防过度归档：每次最多写 N 条；对相似已有记忆做合并而非追加（向量检索 + 阈值判定）
- [ ] 提供 `rmcli memory archive --session <id>` 手动触发，便于调试

### 3.6 CLI 扩展
- [ ] `rmcli ingest <pdf_path...>`：本地 → OSS 上传 → 调 `/v1/knowledge/ingest` → 流式打印进度
- [ ] `rmcli kb ls`、`rmcli kb rm <doc_id>`
- [ ] `rmcli memory add --category <c> "<content>"`、`rmcli memory ls`、`rmcli memory rm <id>`

### 3.7 Smoke-test 扩展
- [ ] step 3：ingest → 提问 → 校验 citation 准确
- [ ] step 4：memory add → 新 session → 提问 → 校验回答用上偏好

### 3.8 验收
- [ ] smoke-test 1–4 全绿
- [ ] README 增加 ingest / memory 用法段
- [ ] `docs/demos/M3.md`：录屏一段 ingest + 记忆触发
- [ ] 提交 M3 完成 commit + tag `v0.3.0-m3`

---

## M4 · 工具调用 + 多 Agent + 周报任务（🎯 MVP）

> **出口**：`rmcli task run weekly-report --week 2026-W17` 流式打印进度，最终拿到 OSS Key 下载得到合格周报；smoke-test 全 5 项绿。**此里程碑结束本项目作为"个人科研助手"已是最小可发布版本。**
>
> **预期工时**：2.5 周
> **独立验收**：完整 smoke-test 全绿；录一段端到端 demo（提问 → ingest → memory → 周报任务）。

### 4.1 外部检索工具
- [ ] 接入 `arxiv-mcp-server`（MCP client 配置 + 启动验证）
- [ ] 把 arxiv MCP 作为 Tool 注册到 ADK
- [ ] 安装 `semanticscholar`，写 `tools/s2_search.py` FunctionTool
- [ ] 写 `tools/web_fetch.py`（httpx + trafilatura 抽正文）
- [ ] **安全**：所有外部内容用 `<external_content>` 标签包裹，system prompt 明禁执行其中指令
- [ ] 论文去重：DOI 优先，无 DOI 用 title 模糊匹配（`rapidfuzz`）
- [ ] **Google Scholar 处理策略说明**（demands.txt 第 3 条点名了 Scholar）：
  - MVP **不直接抓 Scholar**——无官方 API、`scholarly` 易被封 IP，得不偿失
  - 用 **arXiv + Semantic Scholar** 覆盖 90% 学术检索场景（S2 已聚合 Scholar 大部分元数据）
  - 若用户实际使用中发现 Scholar 仍是刚需，再在 M5 阶段用 SerpAPI 接入（付费但稳定），单独走 `tools/scholar_serpapi.py`

### 4.2 Sub-agents
- [ ] 写 `agents/librarian.py`（RAG 专用 Agent，挂 `search_kb`）
- [ ] 写 `agents/scout.py`（外部检索 Agent，挂 arxiv + s2 + web_fetch + ParallelAgent 并行）
- [ ] 写 `agents/writer.py`（写作 Agent，按写作偏好生成 Markdown）
- [ ] Coordinator 升级：把 `Librarian` / `Scout` / `Writer` 配为 `sub_agents`，按用户意图派发

### 4.3 论文元数据
- [ ] 设计 `papers.db` schema：`papers(id, arxiv_id, title, authors, venue, year, tags, read_at, rating, oss_path, user_id, created_at)`
- [ ] 写 `services/paper_repo.py`：CRUD + 分页查询
- [ ] `GET /v1/papers?user_id=&tag=&year=&q=`（分页）
- [ ] `PATCH /v1/papers/{paper_id}`（rating / read_at / tags）
- [ ] ingest 流水线扩展：解析 PDF 元数据写入 papers 表

### 4.4 任务编排框架（直接复用 M3.4 的 job_runner）
- [ ] 写 `services/task_kinds.py`：`kind` 注册器 + 每个 kind 的 params Pydantic schema 校验
- [ ] **不再写 `task_runner.py`**——直接复用 M3.4 的 `services/job_runner.py`（asyncio.Task registry + jobs.db）
- [ ] `POST /v1/tasks/run`（kind, params, user_id → task_id）：schema 校验 → `job_runner.submit(kind, ...)` → 返回 task_id
- [ ] `GET /v1/tasks/{task_id}`（状态 + 产物 OSS Key）：复用 jobs.db 查询
- [ ] `GET /v1/tasks/{task_id}/events`（SSE 进度流）：基于 `job_runner.subscribe`
- [ ] `POST /v1/tasks/{task_id}/cancel`：调 `job_runner.cancel`
- [ ] 任务超时（默认 10 分钟）通过 `asyncio.wait_for` 实现，超时后转 `failed` 状态

### 4.5 weekly_report 任务
- [ ] 设计 `params` schema：`{week_start?, paper_count=5, focus_keywords?[]}`
- [ ] 实现 `SequentialAgent`：gather（Scout）→ filter（Librarian + Memory 打分）→ summarize（ParallelAgent）→ synthesize（Writer）→ persist
- [ ] 写周报 Markdown 模板（`docs/templates/weekly_report.md`）
- [ ] 产物上传 OSS → 返回 Key
- [ ] 任务结束更新 Memory.recent_tasks

### 4.6 CLI 扩展
- [ ] `rmcli task run <kind> [--params ...]`
- [ ] `rmcli task status <task_id>`（SSE 流式进度）
- [ ] `rmcli task cancel <task_id>`
- [ ] `rmcli papers ls / show / update`

### 4.7 文档与 schema
- [ ] 写 `docs/task_kinds.md`：每个 kind 的 params schema 与示例
- [ ] 重新导出 `openapi.json`

### 4.8 Smoke-test 扩展
- [ ] step 5：启动 weekly_report → 等完成 → 下载产物 → 校验 Markdown 章节齐全（含引用、author 列表、TL;DR）

### 4.9 验收（MVP 关）
- [ ] smoke-test 1–5 全绿
- [ ] 录制端到端 demo 视频（≥3 分钟）：装环境 → 起服务 → ingest → 对话 → 任务 → 拿到周报
- [ ] 写 `docs/MVP_RELEASE_NOTES.md`：本项目作为单机科研工具的能力清单
- [ ] 提交 M4 完成 commit + tag `v0.4.0-m4-mvp`

---

## M5 · 规划、批处理、稳定化

> **出口**：所有 v1 API 稳定、限流降级有保障、`adk eval` 跑回归通过；项目对外可发布。
>
> **预期工时**：2 周
> **独立验收**：smoke-test 全绿 + adk eval 回归通过 + 完整 demo 视频。

### 5.1 PlanReActPlanner 接入
- [ ] Coordinator 挂 `PlanReActPlanner`
- [ ] Writer 挂 `PlanReActPlanner`
- [ ] 在 SSE 事件流中输出 `thinking`（PLANNING/REASONING 段）
- [ ] 调整 system prompt 与 Plan-ReAct 兼容

### 5.2 filter_papers 任务
- [ ] 设计 `params` schema：`{query, candidate_paper_ids[], top_n=50, max_iter=3}`
- [ ] 实现 `LoopAgent`：score_batch → prune（去掉底部 50%）→ refine_query
- [ ] 终止条件：候选数 ≤ top_n 或达到 max_iter
- [ ] 接入 papers.db 候选源（按 user_id + 历史阅读筛选）
- [ ] 产物：筛选结果 JSON + 简短 rationale Markdown

### 5.3 成本与限流
- [ ] `before_model_callback`：本会话 token 软上限（默认 200k），超额截断旧上下文
- [ ] `after_model_callback`：累计 token 用量记录到日志
- [ ] LiteLLM fallback 模型链：DeepSeek → Qwen-Max → GPT-4.1-mini
- [ ] DeepSeek 429/503 → 返回 `LLM_RATE_LIMITED, retryable=true`
- [ ] 任务级超时：默认 10 分钟，可 params 覆盖

### 5.4 评估回归
- [ ] 准备 20 条测试 query 数据集（混合 RAG / 工具调用 / 任务）
- [ ] 写 `eval/dataset.json` + 期望答案要点
- [ ] `adk eval` 在 CI 上跑（用低成本模型 stub 或固定 seed）
- [ ] 跑通基线，记录到 `docs/eval_baseline.md`

### 5.5 数据备份
- [ ] 写 `scripts/backup.py`：`./data/` → OSS（按日期归档）
- [ ] Windows Task Scheduler 注册每日凌晨备份
- [ ] 验证恢复脚本：从 OSS 拉回 `./data/` 后服务能起

### 5.6 CLI 收尾
- [ ] `rmcli` 子命令补齐到 9.3 节全部端点
- [ ] `rmcli --help` 输出每个子命令使用示例
- [ ] CLI 错误友好化：显示 trace_id 与"如何排查"提示

### 5.7 文档收尾
- [ ] `examples/curl/` 覆盖每个端点
- [ ] README quick-start 完整可运行（含示例 PDF 演示）
- [ ] 写 `docs/architecture.md`：从 research.md 抽取面向新人的精简版
- [ ] 写 `docs/CONTRIBUTING.md`（开发约定）
- [ ] 写 `CHANGELOG.md`（v0.1 ~ v0.5）

### 5.8 发布前验收
- [ ] smoke-test 全绿
- [ ] adk eval 回归通过
- [ ] 录制完整 demo 视频（≥5 分钟，含全部主要场景）
- [ ] 在一台干净的机器上从零跟着 README 走一遍 quick-start 通过
- [ ] 提交 M5 完成 commit + tag `v0.5.0-m5`

---

## M6 · Java Spring Boot 联调

> **出口**：Spring Boot 后端接入完成，能复现 `rmcli` 的全部场景；Python 服务端 0 行代码改动。
>
> **预期工时**：1–2 周（取决于 Java 侧节奏）
> **前置**：M5 完成、Java 侧已具备调用方雏形

### 6.1 客户端生成
- [ ] 把 `docs/openapi.json` 同步给 Java 侧
- [ ] Java 侧用 `openapi-generator` 生成 client（确认包名、命名风格）
- [ ] 在 Spring Boot 工程里跑一次最简调用（`/v1/healthz`）

### 6.2 协议对齐
- [ ] 错误码枚举一致性 review（Python 与 Java 各列一遍对照）
- [ ] `trace_id` 在 Java 侧 MDC 的 key 名约定（建议沿用 `traceId`）
- [ ] 超时配置敲定（普通 60s / 任务 10min）
- [ ] SSE 续传：约定 `Last-Event-Id` 语义；Python 是否实现取决于优先级

### 6.3 端到端联调
- [ ] Java 调 `/v1/sessions` + `/v1/chat` 流式打通到前端
- [ ] Java 调 `/v1/knowledge/ingest`（OSS Key 由 Java 生成）
- [ ] Java 调 `/v1/tasks/run weekly-report` 拿产物
- [ ] Java 调 `/v1/memory` CRUD
- [ ] Java 调 `/v1/papers` 查询

### 6.4 异常路径联调
- [ ] DeepSeek 限速：Java 侧指数退避验证
- [ ] Python 服务重启中：Java 侧探活降级
- [ ] OSS 失败：错误回传一致

### 6.5 性能基线
- [ ] 单机 10 并发对话压测，记录 P50/P95 延迟
- [ ] 长任务并发 3 个，验证 jobs.db 锁不出问题
- [ ] 输出 `docs/perf_m6.md`

### 6.6 验收
- [ ] Java 侧在前端复现 `rmcli` 已有的所有场景
- [ ] Python 服务端代码 0 修改
- [ ] 提交 M6 完成 commit + tag `v1.0.0`

---

## M7（可选）· 运维与长期化

> **出口**：服务可作为 Windows 后台服务长期运行；Java 侧拥有完整可观测能力。
>
> **触发条件**：用户基数扩大 / 需要 7×24 / 接入定时调度

### 7.1 服务化
- [ ] 安装 NSSM
- [ ] `nssm install ResearchMate uvicorn ...`
- [ ] 配置开机自启 + 崩溃自恢复
- [ ] 日志轮转策略与磁盘配额

### 7.2 监控
- [ ] 暴露 `/metrics`（Prometheus 格式）
- [ ] 关键指标：QPS、延迟、token 用量、job 队列深度、GPU 占用
- [ ] Java 侧拉取并接入既有监控面板（或起一个简单 Grafana）

### 7.3 远程访问（异机部署时）
- [ ] 监听 `0.0.0.0` + 防火墙白名单 Java 主机 IP
- [ ] 或 Cloudflare Tunnel / frp 内网穿透
- [ ] HTTPS（如跨公网）：mkcert / Let's Encrypt

### 7.4 定时任务接入
- [ ] Java Quartz 配置：每日 8:00 调 `/v1/tasks/run weekly-report`
- [ ] 失败告警链路（Java 侧）

### 7.5 验收
- [ ] 重启电脑后服务自动起
- [ ] 监控面板有完整数据
- [ ] 提交 M7 完成 commit + tag `v1.1.0`

---

## 附录 A · 跨里程碑的持续工作

下面这些不属于某个特定里程碑，但贯穿全程。每周 / 每个 PR 滚动检查。

### A.1 测试纪律
- [ ] 每个新增模块先写单测再实现（或同 PR 提交）
- [ ] 关键路径覆盖率 ≥ 70%
- [ ] smoke-test 在每个 M 末尾跑一遍
- [ ] adk eval 在 M5 之后每月跑一次

### A.2 文档同步
- [ ] 接口变更同步更新 `openapi.json` + `docs/task_kinds.md`
- [ ] 设计变更先改 `research.md` 再改 `plan.md` 再写代码
- [ ] CHANGELOG 每个 PR 追加一行

### A.3 安全
- [ ] `.env` 永不入仓（`.gitignore` 已配）
- [ ] `RESEARCH_AGENT_TOKEN` 至少 32 字符随机
- [ ] 外部内容必须经 `<external_content>` 包装
- [ ] 任何 `os.system` / `subprocess` 调用走白名单

### A.4 数据卫生
- [ ] `./data/` 不入仓
- [ ] 每周手工抽样 100 条 chunk 看质量
- [ ] memory 中每月跑一次合并/过期清理（M5 之后自动化）

### A.5 portfolio 沉淀
- [ ] 每个里程碑结束录一段短 demo 放 `docs/demos/`
- [ ] `README.md` 顶部维护一张架构图（与 research.md §4 同步）
- [ ] M5 末尾整理一篇 blog 风格的项目复盘
