# ResearchMate

ResearchMate 是一个本地优先的个人科研助手，基于 Google ADK 构建。当前已完成 M3：可以通过 FastAPI 暴露本地 HTTP/SSE 服务，并用 `rmcli` 完成探活、session 管理、对话、知识库入库和长期记忆管理。

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

5. 手动导入你的 PDF 到本地知识库：

   ```bash
   uv run python scripts/ingest.py /path/to/your-paper.pdf --paper-id paper_X --title "Paper Title"
   ```

   需要一次导入多篇 PDF 时：

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

8. 通过 M3 服务 API 导入 PDF 并保存长期记忆：

   ```bash
   uv run rmcli ingest examples/pdfs/rag_basics.pdf --user-id local --tag sample
   uv run rmcli kb ls --user-id local
   uv run rmcli memory add --category research_direction "我的研究方向是多模态对齐。"
   uv run rmcli memory ls
   ```

   没有配置阿里云 OSS 凭据时，`rmcli ingest` 会把文件写入 `OSS_LOCAL_DIR`，再通过同一套 OSS key 流程提交 `/v1/knowledge/ingest`。配置 `OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`、`OSS_BUCKET`、`OSS_ENDPOINT` 后会自动切换到真实 OSS。

   需要完整 M3 冒烟验证时，在服务运行后执行：

   ```bash
   uv run python scripts/smoke_test.py --steps 1,2,3,4
   ```

## Directory Layout

- `src/researchmate/`：主包，包含 ADK 入口、API、CLI、服务层和工具包装。
- `scripts/`：开发和运维脚本，不参与打包。
- `tests/`：pytest 测试。
- `docs/`：架构、性能基线和开发日志。
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
  --expect-citation "[source: paper_X, p.1]"
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
