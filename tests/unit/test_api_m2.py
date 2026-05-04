from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from researchmate.api.app import create_app
from researchmate.config import Settings

_TOKEN = "x" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        RESEARCH_AGENT_TOKEN=SecretStr(_TOKEN),
        RESEARCH_AGENT_BIND="127.0.0.1:8000",
        ADK_SESSION_DB_URL=f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}",
        CHROMA_DIR=tmp_path / "chroma",
    )


def test_v1_routes_require_internal_token(tmp_path: Path) -> None:
    api = create_app(_settings(tmp_path))

    with TestClient(api) as client:
        response = client.get("/v1/livez")
        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"
        assert response.headers["X-Trace-Id"]


def test_health_routes_with_token(tmp_path: Path) -> None:
    api = create_app(_settings(tmp_path))
    headers = {"X-Internal-Token": _TOKEN}

    with TestClient(api) as client:
        livez = client.get("/v1/livez", headers=headers)
        assert livez.status_code == 200
        assert livez.json()["status"] == "ok"

        readyz = client.get("/v1/readyz", headers=headers)
        assert readyz.status_code == 200
        assert readyz.json()["dependencies"]["session_db"]["ok"] is True
        assert readyz.json()["runtime"]["mode"] in {"cpu", "gpu"}


def test_session_create_get_delete(tmp_path: Path) -> None:
    api = create_app(_settings(tmp_path))
    headers = {"X-Internal-Token": _TOKEN}

    with TestClient(api) as client:
        created = client.post("/v1/sessions", json={"user_id": "tester"}, headers=headers)
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        fetched = client.get(f"/v1/sessions/{session_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["user_id"] == "tester"

        deleted = client.delete(f"/v1/sessions/{session_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json() == {"session_id": session_id, "deleted": True}

        missing = client.get(f"/v1/sessions/{session_id}", headers=headers)
        assert missing.status_code == 404
