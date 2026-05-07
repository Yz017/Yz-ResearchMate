from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from researchmate.api.app import create_app
from researchmate.config import Settings
from researchmate.services.paper_repo import PaperRepository

_TOKEN = "x" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        RESEARCH_AGENT_TOKEN=SecretStr(_TOKEN),
        RESEARCH_AGENT_BIND="127.0.0.1:8000",
        ADK_SESSION_DB_URL=f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}",
        CHROMA_DIR=tmp_path / "chroma",
        OSS_LOCAL_DIR=tmp_path / "oss",
        OSS_CACHE_DIR=tmp_path / "cache",
        JOBS_DB_PATH=tmp_path / "jobs.db",
        PAPERS_DB_PATH=tmp_path / "papers.db",
        EMBEDDING_BACKEND="hashing",
        RERANK_BACKEND="lexical",
        MEMORY_IDLE_SCAN_SECONDS=3600,
    )


def _wait_for_job(
    client: TestClient,
    path: str,
    headers: dict[str, str],
    *,
    timeout_seconds: float = 60.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        payload = response.json()
        if payload["state"] in {"done", "failed", "cancelled", "interrupted"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"job did not finish: {payload}")


def test_filter_papers_task_ranks_and_persists_artifacts(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repo = PaperRepository.from_settings(settings)
    paper_1 = repo.upsert_paper(
        paper_id="filter_1",
        title="Retrieval Augmented Generation for Research Assistants",
        authors=["Alice"],
        user_id="tester",
        tags=["rag", "agent"],
        year=2025,
        read_at="2026-04-21T00:00:00+00:00",
        rating=4.5,
    )
    paper_2 = repo.upsert_paper(
        paper_id="filter_2",
        title="Memory-Aware Planning for Paper Ranking",
        authors=["Bob"],
        user_id="tester",
        tags=["memory", "planning"],
        year=2024,
        read_at="2026-04-22T00:00:00+00:00",
        rating=4.2,
    )
    repo.upsert_paper(
        paper_id="filter_3",
        title="A Survey of Vision Transformers",
        authors=["Carol"],
        user_id="tester",
        tags=["vision"],
        year=2023,
        read_at="2026-04-23T00:00:00+00:00",
        rating=3.8,
    )

    api = create_app(settings)
    headers = {"X-Internal-Token": _TOKEN}

    with TestClient(api) as client:
        submitted = client.post(
            "/v1/tasks/run",
            json={
                "kind": "filter-papers",
                "user_id": "tester",
                "params": {
                    "query": "RAG agent shortlist",
                    "candidate_paper_ids": [paper_1.id, paper_2.id, "filter_3"],
                    "top_n": 2,
                    "max_iter": 2,
                },
            },
            headers=headers,
        )
        assert submitted.status_code == 200
        task_id = submitted.json()["task_id"]
        task_job = _wait_for_job(client, f"/v1/tasks/{task_id}", headers)
        assert task_job["state"] == "done", task_job.get("error")

        result = task_job["result"]
        assert isinstance(result, dict)
        assert result["paper_count"] == 2
        assert isinstance(result["selected_papers"], list)
        assert result["selected_papers"][0]["id"] in {paper_1.id, paper_2.id}
        assert result["artifact_markdown_oss_key"]
        assert result["artifact_json_oss_key"]
