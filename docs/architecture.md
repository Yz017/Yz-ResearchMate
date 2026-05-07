# ResearchMate Architecture

ResearchMate is a local-first research assistant built on Google ADK.

Core layers:

- `src/researchmate/agent.py`: ADK entrypoint that exports `root_agent`.
- `src/researchmate/agents/`: Coordinator and specialist sub-agents for RAG, search, writing, and memory extraction.
- `src/researchmate/api/`: FastAPI service surface for sessions, chat, memory, knowledge, papers, and tasks.
- `src/researchmate/services/`: Pure business logic for storage, jobs, papers, memory, retrieval, and task orchestration.
- `src/researchmate/tools/`: Function tools exposed to ADK agents.
- `scripts/`: Operational helpers such as ingest, smoke tests, and backups.

Runtime storage:

- SQLite for sessions, jobs, and papers.
- Chroma for knowledge chunks and long-term memory.
- OSS or local object storage for uploaded PDFs and generated artifacts.

Operational model:

- `uvicorn researchmate.api:app` runs the service.
- `rmcli` exercises the same HTTP/SSE contract as the Java caller will use later.
- `scripts/smoke_test.py` is the end-to-end contract check for milestone work.
