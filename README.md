# ResearchMate

ResearchMate 是一个本地优先的个人科研助手，基于 Google ADK 构建。当前已完成 M5 稳定化开发：可以通过 FastAPI 暴露本地 HTTP/SSE 服务，并用 `rmcli` 完成探活、session 管理、对话、文档入库、长期记忆、论文元数据、批处理任务、备份和 eval 回归。

## Quick Start

1. 安装 uv：

   ```bash
   winget install astral-sh.uv
   ```

2. 同步依赖：

   ```bash
   uv sync
   ```

3. 复制并填写配置：

   ```bash
   cp .env.example .env
   ```

   至少需要填写 `DEEPSEEK_API_KEY` 才能进行真实 LLM 对话。

4. 验证本地脚手架：

   ```bash
   uv run python -c "import researchmate"
   uv run rmcli --help
   uv run pytest tests/
   ```

5. 手动导入你的文档到本地知识库：

   ```bash
   uv run python scripts/ingest.py /path/to/your-paper.pdf --paper-id paper_X --title "Paper Title"
   ```

   也可以导入 `.txt` / `.md` / `.docx` / `.html` / `.htm`：

   ```bash
   uv run python scripts/ingest.py README.md notes.txt report.docx page.html
   ```

   需要一次导入多篇文档时：

   ```bash
   uv run python scripts/ingest.py /path/to/paper-a.pdf /path/to/paper-b.pdf
   ```

   需要清空并重建当前知识库时，才使用 `--reset`：

   ```bash
   uv run python scripts/ingest.py /path/to/your-paper.pdf --reset
   ```

6. 启动 ADK 调试 UI：

   ```bash
   uv run adk web src/
   ```

   浏览器打开 ADK 输出的本地地址，选择 `researchmate` app 后提问：
   `What does paper_X say about its method?`

7. 启动无头服务并用 CLI 对话：

   ```bash
   uv run uvicorn researchmate.api:app --host 127.0.0.1 --port 8000 --workers 1
   uv run rmcli health
   uv run rmcli session create --user-id local
   uv run rmcli chat "请简短说明 ResearchMate 当前能力。"
   ```

   `rmcli` 默认读取 `.env` 中的 `RESEARCH_AGENT_BIND` 和 `RESEARCH_AGENT_TOKEN`，请求头使用 `X-Internal-Token`。

8. 通过服务 API 导入文档、保存长期记忆并生成周报：

   ```bash
   uv run rmcli ingest examples/pdfs/rag_basics.pdf --user-id local --tag sample
   uv run rmcli kb ls --user-id local
   uv run rmcli memory add --category research_direction "我的研究方向是多模态对齐。"
   uv run rmcli memory ls
   uv run rmcli task run weekly-report --week 2026-W17 --paper-count 5
   ```

   没有配置阿里云 OSS 凭据时，`rmcli ingest` 会把文件写入 `OSS_LOCAL_DIR`，再通过同一套 OSS key 流程提交 `/v1/knowledge/ingest`。配置 `OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`、`OSS_BUCKET`、`OSS_ENDPOINT` 后会自动切换到真实 OSS。

   需要完整 M5 冒烟验证时，在服务运行后执行：

   ```bash
   uv run python scripts/smoke_test.py --steps 1,2,3,4,5,6
   ```

## Directory Layout

- `src/researchmate/`：主包，包含 ADK 入口、API、CLI、服务层和工具包装。
- `scripts/`：开发和运维脚本，不参与打包。
- `tests/`：pytest 测试。
- `docs/`：架构、开发总结、demo、任务说明、性能基线、评测和 OpenAPI 等文档。
- `examples/`：curl 示例和样例 PDF。
- `data/`、`logs/`：运行时数据，已被 `.gitignore` 忽略。

## M0 Commands

```bash
uv sync
uv run python -c "import researchmate"
uv run python -c "from researchmate.agent import root_agent; print(root_agent.name)"
uv run rmcli --help
uv run python scripts/detect_runtime.py
uv run pytest tests/
```

## M1 RAG Commands

```bash
uv run python scripts/check_embeddings.py
uv run python scripts/ingest.py /path/to/your-paper.pdf --paper-id paper_X --title "Paper Title"
uv run python scripts/check_m1_rag_agent.py \
  --prompt "Use the local knowledge base. What does paper_X say about its method?" \
  --expect-citation "[source:"
uv run adk web src/
```

默认 `EMBEDDING_BACKEND=auto` 且 `EMBEDDING_ALLOW_DOWNLOAD=false`：如果本机已经缓存 `BAAI/bge-m3` 与 `BAAI/bge-reranker-v2-m3`，系统会自动使用真实 BGE embedding/rerank；否则退回本地 hashing + lexical，保证离线 CPU 环境也能运行。首次拉取模型时，可先尝试 HuggingFace 官方源；如果不可达，使用镜像源：

```bash
uv run python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3', endpoint='https://hf-mirror.com', ignore_patterns=['imgs/*'])"
uv run python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-reranker-v2-m3', endpoint='https://hf-mirror.com')"
```

## M2 Service Commands

```bash
uv run uvicorn researchmate.api:app --host 127.0.0.1 --port 8000 --workers 1
uv run python -m researchmate.api
uv run rmcli health
uv run rmcli health --deep
uv run rmcli session create --user-id local
uv run rmcli chat "请用一句话说明 ResearchMate 可以做什么。"
uv run python scripts/smoke_test.py --steps 1,2
```

curl 示例在 `examples/curl/`：

```bash
RESEARCH_AGENT_TOKEN="$(grep '^RESEARCH_AGENT_TOKEN=' .env | cut -d= -f2-)" \
  bash examples/curl/quickstart.sh
```

## M3 Memory And Knowledge Commands

```bash
uv run uvicorn researchmate.api:app --host 127.0.0.1 --port 8000 --workers 1
uv run rmcli ingest examples/pdfs/rag_basics.pdf --user-id local --tag sample
uv run rmcli kb ls --user-id local
uv run rmcli memory add --category research_direction "我的研究方向是多模态对齐。"
uv run rmcli memory add --category writing_style "写作偏好是先给结论，再给依据。"
uv run rmcli memory ls --user-id local
uv run rmcli chat --user-id local "请根据长期记忆说明我的研究方向。"
uv run python scripts/smoke_test.py --steps 1,2,3,4
```

## M4 MVP Task Commands

```bash
uv run uvicorn researchmate.api:app --host 127.0.0.1 --port 8000 --workers 1
uv run rmcli ingest examples/pdfs/rag_basics.pdf --user-id local --tag weekly
uv run rmcli papers ls --user-id local
uv run rmcli papers update rag_basics --rating 4.5 --tag weekly --tag read
uv run rmcli task run weekly-report --week 2026-W17 --paper-count 5 --focus-keyword RAG
uv run rmcli task status <task_id> --no-watch
uv run rmcli task run filter-papers --query "RAG agent shortlist" --candidate-paper-id paper_1 --top-n 50
uv run rmcli task kinds
uv run python scripts/smoke_test.py --steps 1,2,3,4,5
```

`weekly_report` 默认只使用本地知识库和 `papers.db`，因此可以离线验收；需要外部候选论文时加 `--include-external`，会调用 arXiv 和 Semantic Scholar。Google Scholar 在当前版本不直接抓取，详见 `docs/task_kinds.md`。

## M5 Stability Commands

```bash
uv run rmcli livez
uv run rmcli version
uv run rmcli memory update <memory_id> --content "..."
uv run rmcli kb job <job_id>
uv run rmcli kb cancel <job_id>
uv run python scripts/backup.py
uv run python scripts/backup.py --restore-key backups/data/<timestamp>.zip --target-dir data-restored
uv run python scripts/smoke_test.py --steps 1,2,3,4,5,6
make eval
```

M5 adds `PlanReActPlanner` on the Coordinator and Writer, `filter_papers` batch ranking, token-budget trimming, model fallback, backup/restore tooling, and an eval seed dataset under `eval/`.
