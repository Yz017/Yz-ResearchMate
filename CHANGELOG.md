# Changelog

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
