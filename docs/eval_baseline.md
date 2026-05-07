# Eval Baseline

This milestone adds a seed `adk eval` dataset under `eval/`.

Run:

```bash
make eval
```

Dataset:

- `eval/dataset.json`: 20 seed query/response cases covering RAG, memory, external search, tasks, backup, and system endpoints.
- `eval/config.json`: baseline scoring thresholds.
- `eval/agent_module/`: deterministic ADK eval stub for CI-safe response-match regression.

Notes:

- The dataset is intentionally concise and should be expanded when the model prompt or tool surface changes.
- The eval stub intentionally avoids external LLM/provider calls so CI can run the baseline without secrets.

Latest baseline:

- 2026-05-07: `make eval` passed 20/20 cases with `response_match_score >= 0.75`.
