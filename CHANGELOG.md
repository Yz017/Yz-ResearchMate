# Changelog

## 0.3.0 - M3

- Added OSS client support with Aliyun OSS operations and a local object-store fallback for offline development.
- Added Chroma-backed long-term memory with CRUD APIs, ADK `MemoryService` registration, `load_memory` and `save_preference` tools, session deletion archival, and idle-session archival.
- Added SQLite-backed async job runner with persisted states, cancellation, SSE progress subscription, interrupted recovery, and traceback capture.
- Added knowledge ingest API over OSS keys, document listing/deletion, and reusable knowledge-base service metadata for user/tag filtering.
- Expanded `rmcli` with `ingest`, `kb`, and `memory` commands.
- Expanded smoke-test steps 3-4 for ingest/citation and memory/new-session behavior.

## 0.2.0 - M2

- Added FastAPI service endpoints for health, version, session CRUD, and chat SSE with internal token auth and trace IDs.
- Added JSON loguru logging, local readiness checks, cached deep LLM health probing, and OpenAPI export support.
- Expanded `rmcli` with service health, session, and SSE chat commands.
- Added M2 curl examples, smoke-test steps 1-2, and unit coverage for auth, health, and session routes.

## 0.1.0 - M1

- Added the local RAG pipeline: PDF extraction/chunking, Chroma vector storage, idempotent ingest with per-PDF rollback, hybrid retrieval, and ADK `search_knowledge_base` tool.
- Added M1 Coordinator agent prompt that requires knowledge-base lookup and `[source: paper_id, p.N]` citations for grounded answers.
- Added offline-first embedding/rerank runtime: `sentence-transformers`/`FlagEmbedding` optional path with hashing + lexical fallback for CPU or no-network environments.
- Completed BGE model cache setup through `hf-mirror.com` after HuggingFace official connectivity failed, and made `auto` prefer cached BGE before fallback.
- Pinned `transformers<5` for `FlagEmbedding` reranker compatibility.
- Added sample PDFs, embedding sanity check, retrieval QA notes, and unit tests for PDF parsing and retrieval.
- Verified `ruff`, `black --check`, `mypy`, pytest, ADK app discovery, sample ingest, and citation-bearing retrieval.

## 0.1.0 - M0

- Initialized ResearchMate project scaffold.
- Added pyproject, configuration loading, minimal ADK root agent, CLI, FastAPI app shell, runtime detection, tests, and CI.
- Verified DeepSeek/LiteLLM hello-world connectivity and ADK web app discovery without recording secret values.

## Development Log - 2026-05-04

- Finished M1 remaining acceptance work without changing the previous changelog entries.
- Confirmed HuggingFace official access was unavailable and used `https://hf-mirror.com` to cache `BAAI/bge-m3` and `BAAI/bge-reranker-v2-m3`.
- Verified cached BGE embedding and reranker run locally on CPU; CUDA remains unavailable because the installed NVIDIA driver is too old for the synced torch build.
- Updated M1 acceptance from recording-based evidence to manual `adk web` acceptance, with verification steps documented in `docs/demos/M1.md`.
- Rebuilt the sample Chroma knowledge base with cached BGE embeddings and reranker, then verified citation retrieval and the M1 ADK Runner smoke path.

## Development Log - 2026-05-04 - M2

- Completed FastAPI serviceization on top of ADK `get_fast_api_app`, while keeping `uvicorn researchmate.api:app` as the stable service entrypoint.
- Added internal `X-Internal-Token` authentication, request trace IDs, JSON log output, unified error bodies, and localhost-only CORS.
- Implemented lightweight `/v1/livez` and `/v1/readyz` checks, cached `/v1/healthz?deep=true`, and `/v1/version` with git/ADK/model/runtime metadata.
- Implemented `/v1/sessions` create/get/delete wrappers over ADK `DatabaseSessionService`, with automatic runtime directory creation for SQLite and Chroma.
- Implemented `/v1/chat/{session_id}` as `text/event-stream`, mapping ADK `Runner.run_async()` events into `thinking`, `tool_call`, `tool_result`, `token`, `citation`, `final`, and `error`.
- Expanded `rmcli` with service health, session management, and interactive or one-shot SSE chat commands through the same HTTP contract Spring Boot will use later.
- Replaced the old scaffold smoke test with `scripts/smoke_test.py --steps 1,2`, covering health checks plus session creation and chat SSE integrity.
- Exported `docs/openapi.json`, added `examples/curl/` scripts, documented M2 service commands in README, and marked M2 complete in `plan.md`.
- Verified `ruff`, `black --check`, `mypy`, full pytest, and live `scripts/smoke_test.py --steps 1,2`; created commit `8b545b9` and tag `v0.2.0-m2`.

## Development Log - 2026-05-04 - M3

- Completed local-first OSS ingestion: real Aliyun OSS is used when credentials are configured; otherwise `OSS_LOCAL_DIR` provides the same key-based flow for development and tests.
- Implemented `memory_records` in Chroma with categories, user scope, timestamps, optional expiry, direct CRUD, search, and expiry sweep.
- Registered ResearchMate memory with ADK Runner and added Coordinator tools for memory load/save; chat requests now preload relevant user memory for stable new-session behavior.
- Implemented `jobs.db` plus an asyncio task registry for queued/running/done/failed/interrupted/cancelled states and SSE job progress.
- Added `/v1/memory/*`, `/v1/knowledge/ingest`, `/v1/knowledge/jobs/*`, and `/v1/knowledge/documents/*` routes.
- Added `rmcli ingest`, `rmcli kb ls/rm`, `rmcli memory add/ls/rm/archive`, M3 docs, and smoke-test steps 3-4.

## 0.4.0 - M4 MVP

- Added Librarian, Scout, and Writer sub-agents under the Coordinator for RAG, external search, and Markdown writing responsibilities.
- Added arXiv, Semantic Scholar, and web-fetch tools with `<external_content>` prompt-injection boundaries; arXiv MCP is registered when an `arxiv-mcp-server` executable is available, with the official arXiv API tool as fallback.
- Added SQLite `papers.db` metadata repository, ingest-to-paper indexing, `/v1/papers` APIs, and `rmcli papers` commands.
- Added reusable task-kind validation plus `/v1/tasks/run`, `/v1/tasks/{id}`, `/v1/tasks/{id}/events`, and cancellation APIs backed by the existing `JobRunner`.
- Added `weekly_report` task generation with local-first paper ranking, memory-aware context, Markdown artifact upload to OSS/local storage, and `recent_tasks` memory updates.
- Added `rmcli task run/status/cancel`, `docs/task_kinds.md`, `docs/templates/weekly_report.md`, M4 demo notes, MVP release notes, refreshed OpenAPI, and smoke-test step 5.
- Verified `ruff`, `black --check`, `mypy`, full pytest, and live `scripts/smoke_test.py --steps 1,2,3,4,5`.
