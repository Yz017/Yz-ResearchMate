# Changelog

## 0.1.0 - M1

- Added the local RAG pipeline: PDF extraction/chunking, Chroma vector storage, idempotent ingest with per-PDF rollback, hybrid retrieval, and ADK `search_knowledge_base` tool.
- Added M1 Coordinator agent prompt that requires knowledge-base lookup and `[source: paper_id, p.N]` citations for grounded answers.
- Added offline-first embedding/rerank runtime: `sentence-transformers`/`FlagEmbedding` optional path with hashing + lexical fallback for CPU or no-network environments.
- Added sample PDFs, embedding sanity check, retrieval QA notes, and unit tests for PDF parsing and retrieval.
- Verified `ruff`, `black --check`, `mypy`, pytest, ADK app discovery, sample ingest, and citation-bearing retrieval.

## 0.1.0 - M0

- Initialized ResearchMate project scaffold.
- Added pyproject, configuration loading, minimal ADK root agent, CLI, FastAPI app shell, runtime detection, tests, and CI.
- Verified DeepSeek/LiteLLM hello-world connectivity and ADK web app discovery without recording secret values.
