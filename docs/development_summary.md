# ResearchMate 开发总结

更新时间：2026-05-25

## 当前状态

ResearchMate 当前本地版本为 `0.5.0`，本地 `main` 分支已推进到 M5 稳定化里程碑，当前 HEAD 为 `8098a84`，标签为 `dev-M5`。本文档按当前源码状态更新；工作区存在本地未提交改动，不能把它当作发布基线。

按 `plan.md` 和现有提交记录，截至目前已经完成 M0 到 M5：

| 里程碑 | 主题 | 状态 |
| --- | --- | --- |
| M0 | 项目初始化与脚手架 | 已完成 |
| M1 | RAG + 对话骨架 | 已完成 |
| M2 | FastAPI 服务化 + CLI 雏形 | 已完成 |
| M3 | Memory + 知识库 API | 已完成 |
| M4 | 工具调用 + 多 Agent + 周报任务 MVP | 已完成 |
| M5 | 规划、批处理、稳定化 | 已完成 |
| M6 | Java Spring Boot 联调 | 未开始 |
| M7 | 运维与长期化 | 未开始 |

## 总体能力

ResearchMate 已经从项目脚手架演进为一个本地优先的个人科研助手。当前可通过 ADK Agent、FastAPI HTTP/SSE 服务和 `rmcli` 三种方式运行，支持本地 PDF/TXT/Markdown/DOCX/HTML 入库、引用型知识库问答、长期记忆、论文元数据管理、异步任务、周报生成、论文筛选、备份恢复和离线 eval 回归。

核心运行入口包括：

- ADK 入口：`src/researchmate/agent.py`
- FastAPI 服务：`researchmate.api:app`
- CLI 命令：`rmcli`
- 端到端冒烟脚本：`scripts/smoke_test.py`
- 备份恢复脚本：`scripts/backup.py`

## 已完成内容

### 1. 项目基础设施

已经完成标准 Python 工程化结构：

- 使用 `src/` layout，主包位于 `src/researchmate/`。
- 使用 `uv` 管理依赖和锁文件，`uv.lock` 已入仓。
- `pyproject.toml` 已配置项目元数据、运行依赖、可选 RAG/OCR 依赖、开发依赖和工具配置。
- 已接入 `ruff`、`black`、`mypy`、`pytest`、pre-commit 和 GitHub Actions CI。
- 已提供 `Makefile`，包含 `serve`、`test`、`lint`、`format`、`smoke-m2`、`smoke-m5`、`backup`、`eval` 等常用目标。
- 已实现统一配置模块 `src/researchmate/config.py`，通过 `.env` 读取 DeepSeek、OSS、会话库、Chroma、RAG、LLM fallback、token budget 等配置。

### 2. ADK Agent 体系

当前 Agent 体系已经从单 Agent 扩展为 Coordinator + 专家子 Agent：

- `Coordinator`：顶层调度 Agent，挂载 `PlanReActPlanner`，负责本地知识库、长期记忆、外部检索和写作任务的协调。
- `Librarian`：本地 RAG 专家，要求回答论文事实前必须检索知识库，并输出 `[source: paper_id, p.N]` 引用。
- `Scout`：外部学术检索专家，支持 arXiv、Semantic Scholar 和网页正文抽取；可选接入 `arxiv-mcp-server`，未安装时使用官方 arXiv API fallback。
- `Writer`：Markdown 写作专家，挂载 `PlanReActPlanner`，用于周报、报告和研究笔记写作。
- `Memory Curator`：后台记忆整理 Agent，用于从会话或任务摘要中抽取稳定长期事实。

M5 已加入统一 LLM 策略：

- 请求上下文 token 软限制裁剪。
- LLM usage 记录。
- DeepSeek 主模型和 fallback 模型链。
- 统一的可重试 LLM 错误分类。

### 3. 本地 RAG 知识库

M1 已完成可离线运行的本地 RAG 管线，当前源码已扩展为多格式文档入库：

- 文档解析：统一入口为 `parse_document_to_chunks`，支持 `.pdf`、`.txt`、`.md`、`.markdown`、`.docx`、`.html`、`.htm`。
- PDF 文本抽取：优先 `pdfplumber`，失败后 fallback 到 `pypdf`。
- TXT/Markdown/DOCX/HTML 会抽取正文和标题结构，单页文档优先用 section citation。
- 分块：保留页码、section、标题、paper_id、source_path、oss_key、user_id、tags、ingested_at 等元数据。
- 向量存储：使用 Chroma，本地 collection 为 `kb_chunks`。
- Embedding：默认 `auto`，优先使用缓存的 `BAAI/bge-m3`，不可用时 fallback 到本地 hashing embedding。
- Rerank：优先使用缓存的 `BAAI/bge-reranker-v2-m3`，不可用时 fallback 到 lexical reranker。
- 检索策略：dense top-k + lexical sparse top-k + RRF 融合 + rerank。
- 知识库工具：`search_knowledge_base` 暴露给 ADK Agent。
- 本地脚本：`scripts/ingest.py` 支持本地多格式文档入库、重复入库去重和失败回滚。

当前示例 PDF 位于 `examples/pdfs/`，用于 README quick-start、smoke test 和检索测试。

### 4. FastAPI HTTP/SSE 服务

M2 到 M5 已完成稳定服务化能力，主要接口包括：

- `GET /v1/livez`：进程存活检查。
- `GET /v1/readyz`：本地依赖就绪检查。
- `GET /v1/healthz`：健康检查，支持 `deep=true` 执行缓存 LLM 探测。
- `GET /v1/version`：版本、git、ADK、模型和运行时元数据。
- `POST /v1/sessions`、`GET /v1/sessions/{session_id}`、`DELETE /v1/sessions/{session_id}`：会话管理。
- `POST /v1/chat/{session_id}`：SSE 对话流。
- `/v1/memory/*`：长期记忆 CRUD 和会话归档。
- `/v1/knowledge/ingest`、`/v1/knowledge/jobs/*`、`/v1/knowledge/documents/*`：知识库异步入库、任务状态、事件流、文档列表和删除。
- `/v1/papers/*`：论文元数据列表、详情和更新。
- `/v1/tasks/*`：异步任务提交、状态、事件流、取消和任务类型查询。

服务侧已实现：

- `X-Internal-Token` 内部鉴权。
- `X-Trace-Id` 请求追踪。
- loguru JSON 日志。
- 统一错误响应 `{code, message, trace_id, retryable}`。
- localhost CORS 限制。
- SSE 事件映射，包括 `thinking`、`tool_call`、`tool_result`、`token`、`citation`、`final`、`error`。

### 5. CLI 独立操作能力

`rmcli` 已能覆盖主要服务契约，可脱离前端独立验收：

- `rmcli livez`、`rmcli health`、`rmcli version`
- `rmcli session create|get|delete`
- `rmcli chat`
- `rmcli ingest`
- `rmcli kb ls|rm|job|cancel|events`
- `rmcli memory add|ls|update|rm|archive`
- `rmcli papers ls|show|update`
- `rmcli task kinds|run|status|cancel`

CLI 默认读取 `.env` 中的 `RESEARCH_AGENT_BIND` 和 `RESEARCH_AGENT_TOKEN`，请求头使用 `X-Internal-Token`，因此它和后续 Java 调用方使用同一套 HTTP/SSE 合约。

### 6. 长期记忆

M3 已完成 Chroma-backed 长期记忆系统：

- collection 为 `memory_records`。
- 支持 `research_direction`、`advisor_requirements`、`writing_style`、`recent_tasks` 四类记忆。
- 支持新增、查询、更新、删除、过期时间、过期清理、向量搜索和 lexical fallback。
- ADK Runner 已注册 `ResearchMemoryService`。
- Agent 可通过 `load_memory` 和 `save_preference` 工具读取和写入记忆。
- 会话删除时会归档会话记忆；服务后台也会按空闲时间扫描并归档。
- 对话前会预加载相关用户记忆，但记忆只作为个性化和任务上下文，不作为论文事实来源。

### 7. OSS 与本地对象存储

M3 已加入 OSS 抽象：

- 配置阿里云 OSS 凭据时使用真实 OSS。
- 未配置 OSS 凭据时使用 `OSS_LOCAL_DIR` 本地 fallback。
- 同一套 key-based 流程用于文档上传、知识库入库、任务产物保存和备份恢复。
- CLI 的 `rmcli ingest` 会先上传本地文档到 OSS/local store，再提交 `/v1/knowledge/ingest`。

### 8. 异步任务系统

M3 已实现 `JobRunner`：

- SQLite 状态库 `jobs.db`。
- 支持 `queued`、`running`、`done`、`failed`、`interrupted`、`cancelled` 状态。
- 支持进度更新、SSE 订阅、取消、启动恢复时把遗留 running 任务标记为 interrupted。
- 知识库入库任务和业务任务共用同一个任务运行器。

M4/M5 已在任务系统上实现两类业务任务：

- `weekly_report`：从本地论文历史和可选外部候选生成 Markdown 周报。
- `filter_papers`：对候选论文进行多轮打分、剪枝和 query refine，输出 JSON 与 Markdown 产物。

### 9. 论文元数据管理

M4 已加入 SQLite `papers.db`：

- 入库文档会同步写入论文元数据。
- 支持 title、authors、venue、year、tags、read_at、rating、doi、arxiv_id、oss_path、user_id 等字段。
- 提供 `/v1/papers` API 和 `rmcli papers` 命令。
- `weekly_report` 和 `filter_papers` 会读取 `papers.db` 作为本地候选来源。

### 10. 外部检索工具

M4 已实现外部检索工具：

- `arxiv_search`
- `s2_search`
- `web_fetch`

外部网页内容使用 `<external_content>` 边界标记，Agent prompt 明确要求不能执行远程内容中的指令。Google Scholar 暂不直接抓取；如未来必须接入，计划使用 SerpAPI 作为单独工具或任务。

### 11. 周报与论文筛选

`weekly_report` 已支持：

- 默认本地优先、离线可验收。
- 可选 `include_external=true` 查询 arXiv 和 Semantic Scholar。
- 按周、论文数量、focus keywords 生成 Markdown。
- 产物上传到 OSS/local store。
- 写入 `recent_tasks` 长期记忆。

`filter_papers` 已支持：

- 指定候选论文 ID，或默认读取用户本地论文历史。
- 按 query、tags、title、venue、authors、记忆、年份、rating、read_at 等信号评分。
- 多轮 prune/refine。
- 输出 JSON 结果和 Markdown rationale。
- 产物上传到 OSS/local store。
- 写入 `recent_tasks` 长期记忆。

### 12. 备份、恢复与回归验证

M5 已完成稳定化工具：

- `scripts/backup.py` 支持把 `data/` 打 zip 后上传到 OSS/local store。
- `scripts/backup.py --restore-key ... --target-dir ...` 支持恢复。
- restore 过程校验 zip 成员路径，避免不安全路径写出。
- `eval/` 下已有 deterministic ADK eval seed dataset。
- `make eval` 使用 `adk eval` 对 20 条 seed case 做 CI-safe 回归，不依赖外部 LLM/provider。

最近一次源码级验证结果：

- `ruff check src tests scripts` 通过。
- `pytest tests/unit` 通过，43 passed。
- 离线脚本入库验证通过：`README.md` 9 chunks，`examples/pdfs/rag_basics.pdf` 3 chunks。
- M5 历史基线仍记录在 `docs/eval_baseline.md`：`make eval` 通过 20/20。

本次文档整理没有重新执行完整服务冒烟、mypy、black 或 eval。

## 当前目录职责

- `src/researchmate/agents/`：Coordinator、Librarian、Scout、Writer、Memory Curator 和 LLM 策略。
- `src/researchmate/api/`：FastAPI 应用、schema、中间件和业务路由。
- `src/researchmate/cli/`：Typer CLI 客户端。
- `src/researchmate/services/`：RAG、文档解析、Chroma、Memory、OSS、JobRunner、PaperRepo、TaskKinds 等业务服务。
- `src/researchmate/tools/`：暴露给 ADK Agent 的工具包装。
- `scripts/`：入库、冒烟、运行时检测、embedding 检查、备份恢复等脚本。
- `tests/unit/`：单元测试，覆盖配置、API、JobRunner、Memory、OSS、文档解析、PaperRepo、Retriever、LLM policy、TaskKinds 等。
- `docs/`：架构、开发日志、OpenAPI、任务类型、性能基线、eval 基线、demo notes、MVP release notes。
- `examples/`：curl 示例和样例 PDF。

## 主要技术选型

- Python：`>=3.11,<3.13`
- Agent 框架：Google ADK
- LLM 调用：LiteLLM，默认 DeepSeek，支持 fallback 模型链
- API：FastAPI + SSE
- CLI：Typer + httpx
- 本地向量库：Chroma
- 本地数据库：SQLite，包括 sessions、jobs、papers
- 文档解析：pdfplumber + pypdf + charset-normalizer + markdown-it-py + DOCX XML 解析 + BeautifulSoup
- Embedding/Rerank：BGE 可选，本地 hashing/lexical fallback
- 对象存储：Aliyun OSS 或本地 fallback
- 测试与质量：pytest、ruff、black、mypy、ADK eval

## 尚未完成和待确认事项

根据 `plan.md`，M6 和 M7 尚未开始：

- M6：Java Spring Boot 联调。
- M7：运维与长期化能力。

历史 release 记录曾列出部分 release-only 手工项未完成：

- Windows Task Scheduler 注册。
- Demo 视频。
- 干净机器 quick-start 验证。
- M5 正式 commit/tag 的发布手续；当前本地已有 `dev-M5` 标签。

此外，当前 MVP 的已知边界包括：

- Google Scholar 不直接抓取。
- `weekly_report` 目前生成 Markdown，DOCX/PDF 导出仍是后续工作。
- 扫描版 PDF 仍需 OCR 预处理；当前 HTML 入库只解析本地文件，不递归抓取链接；DOCX 表格不是当前解析重点。
- 本地 CPU 环境可运行，但 BGE embedding/rerank 在 CPU 下速度较慢；无缓存模型时会 fallback 到 hashing/lexical。
