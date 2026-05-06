# ResearchMate Task Kinds

This document is the human-readable contract for `/v1/tasks/run`.

## `weekly_report`

Generate a Markdown weekly reading report and upload it to OSS/local object storage.

Request:

```json
{
  "kind": "weekly_report",
  "user_id": "local",
  "params": {
    "week_start": "2026-04-20",
    "paper_count": 5,
    "focus_keywords": ["RAG", "memory"],
    "include_external": false,
    "timeout_seconds": 600
  }
}
```

Parameters:

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `week_start` | `date \| null` | current week Monday | ISO date. CLI `--week 2026-W17` maps to `2026-04-20`. |
| `paper_count` | `integer` | `5` | Range `1..20`. |
| `focus_keywords` | `string[]` | `[]` | Used for local paper ranking and optional external search query. |
| `include_external` | `boolean` | `false` | When `true`, Scout tools query arXiv and Semantic Scholar. Smoke tests keep this `false` for offline determinism. |
| `timeout_seconds` | `number` | `600` | Range `10..3600`; enforced with `asyncio.wait_for`. |

Response from `POST /v1/tasks/run`:

```json
{
  "task_id": "uuid"
}
```

Final task result from `GET /v1/tasks/{task_id}`:

```json
{
  "result": {
    "artifact_oss_key": "artifacts/weekly_reports/local/2026-04-20/<task_id>.md",
    "artifact_url": "file:///...",
    "week_start": "2026-04-20",
    "week_end": "2026-04-26",
    "paper_count": 5,
    "papers": [
      {
        "id": "paper_id",
        "title": "Paper title",
        "authors": ["Author A"],
        "citation": "[source: paper_id, p.1]",
        "source": "local"
      }
    ]
  }
}
```

Generated Markdown must include:

- `## TL;DR`
- `## Candidate Papers`
- author lists
- evidence/citation lines
- `## Citations`

## Google Scholar Policy

MVP does not directly scrape Google Scholar. Scholar has no official public API and `scholarly`-style scraping is brittle and likely to trigger IP blocks. ResearchMate uses arXiv plus Semantic Scholar for M4. If Scholar becomes a hard requirement, M5 should add a paid SerpAPI-backed `scholar_serpapi` tool.

## arXiv MCP Policy

Scout includes an optional ADK MCP hook for `arxiv-mcp-server`: if an `arxiv-mcp-server` executable is present on `PATH`, it is registered as an MCP toolset. Service startup does not require that server; the bundled official arXiv API FunctionTool remains the deterministic fallback.
