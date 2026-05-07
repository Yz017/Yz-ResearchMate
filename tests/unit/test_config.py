from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from researchmate.config import Settings


def test_settings_parse_bind_and_token() -> None:
    settings = Settings(
        RESEARCH_AGENT_TOKEN=SecretStr("x" * 32),
        RESEARCH_AGENT_BIND="127.0.0.1:8000",
        ADK_SESSION_DB_URL="sqlite+aiosqlite:///./data/sessions.db",
    )

    assert settings.bind_host == "127.0.0.1"
    assert settings.bind_port == 8000
    assert settings.embedding_device == "auto"
    assert settings.embedding_backend == "auto"
    assert settings.kb_collection == "kb_chunks"
    assert settings.memory_collection == "memory_records"
    assert settings.jobs_db_path.as_posix().endswith("data/jobs.db")
    assert settings.rag_final_k == 5
    assert settings.llm_fallback_models == ["qwen/qwen-max", "openai/gpt-4.1-mini"]
    assert settings.llm_token_soft_limit == 200_000


def test_settings_reject_short_token() -> None:
    with pytest.raises(ValidationError):
        Settings(RESEARCH_AGENT_TOKEN=SecretStr("too-short"))


def test_settings_reject_plain_sqlite_path() -> None:
    with pytest.raises(ValidationError):
        Settings(
            RESEARCH_AGENT_TOKEN=SecretStr("x" * 32),
            ADK_SESSION_DB_URL="./data/sessions.db",
        )


def test_settings_reject_empty_collection_name() -> None:
    with pytest.raises(ValidationError):
        Settings(
            RESEARCH_AGENT_TOKEN=SecretStr("x" * 32),
            KB_COLLECTION="   ",
        )
