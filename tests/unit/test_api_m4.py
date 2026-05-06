from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from researchmate.api.app import create_app
from researchmate.config import Settings
from researchmate.services.oss_client import OssClient

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


def test_papers_api_and_weekly_report_task(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    oss_key = OssClient(settings).put_file(
        Path("examples/pdfs/rag_basics.pdf"),
        key="tests/m4_rag_basics.pdf",
    )
    api = create_app(settings)
    headers = {"X-Internal-Token": _TOKEN}

    with TestClient(api) as client:
        submitted = client.post(
            "/v1/knowledge/ingest",
            json={
                "oss_keys": [oss_key],
                "owner_user_id": "tester",
                "tags": ["m4"],
                "paper_id": "api_m4_rag_basics",
                "title": "RAG Basics",
            },
            headers=headers,
        )
        assert submitted.status_code == 200
        ingest_job_id = submitted.json()["job_id"]
        ingest_job = _wait_for_job(
            client,
            f"/v1/knowledge/jobs/{ingest_job_id}",
            headers,
        )
        assert ingest_job["state"] == "done", ingest_job.get("error")

        papers = client.get("/v1/papers?user_id=tester&tag=m4", headers=headers)
        assert papers.status_code == 200
        assert papers.json()["items"][0]["id"] == "api_m4_rag_basics"

        patched = client.patch(
            "/v1/papers/api_m4_rag_basics",
            json={"rating": 4.0, "tags": ["m4", "read"]},
            headers=headers,
        )
        assert patched.status_code == 200
        assert patched.json()["rating"] == 4.0

        task = client.post(
            "/v1/tasks/run",
            json={
                "kind": "weekly-report",
                "user_id": "tester",
                "params": {
                    "week_start": "2026-04-20",
                    "paper_count": 1,
                    "focus_keywords": ["RAG"],
                    "include_external": False,
                },
            },
            headers=headers,
        )
        assert task.status_code == 200
        task_id = task.json()["task_id"]
        task_job = _wait_for_job(client, f"/v1/tasks/{task_id}", headers)
        assert task_job["state"] == "done", task_job.get("error")
        result = task_job["result"]
        assert isinstance(result, dict)
        artifact_key = result["artifact_oss_key"]
        assert isinstance(artifact_key, str)

        report_path = OssClient(settings).get_file(artifact_key, tmp_path / "report.md")
        report = report_path.read_text(encoding="utf-8")
        assert "## TL;DR" in report
        assert "## Candidate Papers" in report
        assert "Authors:" in report
        assert "[source: api_m4_rag_basics, p." in report
