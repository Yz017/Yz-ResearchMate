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
| `week_start` | `date \| null` | current week Monday (UTC) | ISO date. CLI `--week 2026-W17` maps to `2026-04-20`. |
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

## `filter_papers`

Rank a paper candidate set and prune it into a relevant shortlist.

Request:

```json
{
  "kind": "filter_papers",
  "user_id": "local",
  "params": {
    "query": "RAG agent shortlist",
    "candidate_paper_ids": ["paper_a", "paper_b"],
    "top_n": 50,
    "max_iter": 3,
    "timeout_seconds": 600
  }
}
```

Parameters:

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `query` | `string` | required | Relevance target used for scoring and query refinement. |
| `candidate_paper_ids` | `string[]` | `[]` | Optional explicit candidate set. Empty means load the user's local paper history from `papers.db`. |
| `top_n` | `integer` | `50` | Range `1..200`. |
| `max_iter` | `integer` | `3` | Range `1..10`; each round scores, prunes the lower half, and refines the query. |
| `timeout_seconds` | `number` | `600` | Range `10..3600`; enforced with `asyncio.wait_for`. |

Final task result:

```json
{
  "result": {
    "artifact_json_oss_key": "artifacts/filter_papers/local/<task_id>.json",
    "artifact_markdown_oss_key": "artifacts/filter_papers/local/<task_id>.md",
    "paper_count": 50,
    "selected_papers": [
      {
        "id": "paper_id",
        "title": "Paper title",
        "score": 4.5,
        "rationale": "title overlap=2; tags overlap=1; memory overlap=0"
      }
    ]
  }
}
```

## Google Scholar Policy

ResearchMate does not directly scrape Google Scholar. Scholar has no official public API and `scholarly`-style scraping is brittle and likely to trigger IP blocks. ResearchMate uses arXiv plus Semantic Scholar by default. If Scholar becomes a hard requirement, add a paid SerpAPI-backed `scholar_serpapi` tool as a separate task kind/tool.

## arXiv MCP Policy

Scout includes an optional ADK MCP hook for `arxiv-mcp-server`: if an `arxiv-mcp-server` executable is present on `PATH`, it is registered as an MCP toolset. Service startup does not require that server; the bundled official arXiv API FunctionTool remains the deterministic fallback.
