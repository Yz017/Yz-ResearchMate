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
        EMBEDDING_BACKEND="hashing",
        RERANK_BACKEND="lexical",
        MEMORY_IDLE_SCAN_SECONDS=3600,
    )


def test_memory_api_crud(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    api = create_app(settings)
    headers = {"X-Internal-Token": _TOKEN}

    with TestClient(api) as client:
        created = client.post(
            "/v1/memory",
            json={
                "user_id": "tester",
                "category": "research_direction",
                "content": "我关注多模态检索。",
            },
            headers=headers,
        )
        assert created.status_code == 200
        memory_id = created.json()["id"]

        listed = client.get("/v1/memory?user_id=tester", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["count"] == 1

        patched = client.patch(
            f"/v1/memory/{memory_id}",
            json={"content": "我关注多模态对齐。"},
            headers=headers,
        )
        assert patched.status_code == 200
        assert "对齐" in patched.json()["content"]

        deleted = client.delete(f"/v1/memory/{memory_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True


def test_knowledge_ingest_job_and_document_api(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sample_pdf = Path("examples/pdfs/rag_basics.pdf")
    oss_key = OssClient(settings).put_file(sample_pdf, key="tests/rag_basics.pdf")
    api = create_app(settings)
    headers = {"X-Internal-Token": _TOKEN}

    with TestClient(api) as client:
        submitted = client.post(
            "/v1/knowledge/ingest",
            json={
                "oss_keys": [oss_key],
                "owner_user_id": "tester",
                "tags": ["sample"],
                "paper_id": "api_m3_rag_basics",
                "title": "RAG Basics",
            },
            headers=headers,
        )
        assert submitted.status_code == 200
        job_id = submitted.json()["job_id"]

        job_payload = None
        for _ in range(120):
            job = client.get(f"/v1/knowledge/jobs/{job_id}", headers=headers)
            assert job.status_code == 200
            job_payload = job.json()
            if job_payload["state"] in {"done", "failed", "cancelled", "interrupted"}:
                break
            time.sleep(0.05)

        assert job_payload is not None
        assert job_payload["state"] == "done", job_payload.get("error")

        documents = client.get(
            "/v1/knowledge/documents?user_id=tester&tag=sample",
            headers=headers,
        )
        assert documents.status_code == 200
        items = documents.json()["items"]
        assert items
        assert items[0]["doc_id"] == "api_m3_rag_basics"
        assert items[0]["chunks"] > 0

        deleted = client.delete(
            "/v1/knowledge/documents/api_m3_rag_basics",
            headers=headers,
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted_chunks"] > 0
