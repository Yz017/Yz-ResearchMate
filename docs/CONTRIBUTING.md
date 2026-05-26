# Contributing

## Code

- Keep changes scoped to the smallest module that owns the behavior.
- Prefer the existing service/tool/agent split over adding new cross-cutting abstractions.
- Use `apply_patch` for edits and keep formatting consistent with `ruff` and `black`.

## Tests

- Add or update unit tests for new behavior.
- Keep smoke-test coverage aligned with API and CLI changes.
- Avoid network-dependent assertions unless the feature is explicitly about external services.

## Runtime data

- Do not commit `data/`, `logs/`, `.env`, or generated artifacts.
- Treat OSS/local object storage as the canonical artifact layer for backups and reports.

## Milestones

- Update `plan.md` when milestone scope changes.
- If `CHANGELOG.md` exists and is part of the current release flow, append a new entry without rewriting earlier history.
