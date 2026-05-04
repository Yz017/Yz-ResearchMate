# ResearchMate

ResearchMate 是一个本地优先的个人科研助手，基于 Google ADK 构建。当前已完成 M1：可以解析本地 PDF、写入 Chroma 知识库，并通过 ADK agent 调用 RAG 检索工具生成带来源引用的回答。

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
