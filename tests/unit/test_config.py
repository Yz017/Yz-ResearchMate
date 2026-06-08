from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from researchmate.config import Settings


def test_settings_parse_bind_and_token() -> None:
    settings = Settings(
        RESEARCH_AGENT_TOKEN=SecretStr("x" * 32),
        RESEARCH_AGENT_BIND="127.0.0.1:8000",
        ADK_SESSION_DB_URL="sqlite+aiosqlite:///./data/sessions.db",
        EMBEDDING_DEVICE="auto",
        EMBEDDING_BACKEND="auto",
        KB_COLLECTION="kb_chunks",
        MEMORY_COLLECTION="memory_records",
        JOBS_DB_PATH=Path("./data/jobs.db"),
        RAG_FINAL_K=5,
        RESEARCHMATE_LLM_FALLBACK_MODELS="qwen/qwen-max,openai/gpt-4.1-mini",
        INGEST_OCR_ENABLED=False,
        OCR_MIN_CHARS=20,
        OCR_GOOD_CHARS=80,
        OCR_LANGUAGES="chi_sim+eng",
        OCR_DPI=300,
        OCR_MAX_PAGES=80,
        TESSERACT_CMD=None,
        LLM_TOKEN_SOFT_LIMIT=200_000,
    )

    assert settings.bind_host == "127.0.0.1"
    assert settings.bind_port == 8000
    assert settings.embedding_device == "auto"
    assert settings.embedding_backend == "auto"
    assert settings.kb_collection == "kb_chunks"
    assert settings.memory_collection == "memory_records"
    assert settings.jobs_db_path.as_posix().endswith("data/jobs.db")
    assert settings.rag_final_k == 5
    assert settings.rag_multi_query_enabled is True
    assert settings.rag_multi_query_variants == 3
    assert settings.rag_multi_query_pool_k == 20
    assert settings.rag_hyde_enabled is True
    assert settings.rag_hyde_docs == 1
    assert settings.rag_hyde_pool_k == 20
    assert settings.ingest_ocr_enabled is False
    assert settings.ocr_min_chars == 20
    assert settings.ocr_good_chars == 80
    assert settings.ocr_languages == "chi_sim+eng"
    assert settings.ocr_dpi == 300
    assert settings.ocr_max_pages == 80
    assert settings.tesseract_cmd is None
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
