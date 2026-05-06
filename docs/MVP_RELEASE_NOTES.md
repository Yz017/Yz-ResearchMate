# ResearchMate MVP Release Notes

M4 turns ResearchMate into a minimum viable local research assistant.

## Included Capabilities

- Local RAG over ingested PDFs with citation-grounded answers.
- Long-term memory for research direction, advisor requirements, writing style, and recent tasks.
- External search tools for arXiv, Semantic Scholar, and web-page text extraction.
- Multi-agent Coordinator with Librarian, Scout, and Writer sub-agents.
- SQLite `papers.db` metadata index with API and CLI access.
- Reusable `/v1/tasks/*` async task API backed by the same `JobRunner` used for ingest jobs.
- `weekly_report` task that generates a Markdown artifact in OSS/local object storage.
- `rmcli task` and `rmcli papers` commands for standalone operation.

## MVP Limits

- Google Scholar is intentionally not scraped in M4; use arXiv and Semantic Scholar, with SerpAPI left for M5 if needed.
- `weekly_report` is deterministic and local-first by default. Set `include_external=true` to query external sources.
- Generated weekly reports are Markdown artifacts; DOCX/PDF export remains future work.

## Verification

- `scripts/smoke_test.py --steps 1,2,3,4,5`
- `rmcli task run weekly-report --week 2026-W17 --paper-count 5`
- `rmcli papers ls --user-id local`
