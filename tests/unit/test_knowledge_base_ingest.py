from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from researchmate.config import Settings
from researchmate.services.embeddings import HashingEmbeddingBackend
from researchmate.services.knowledge_base import KnowledgeBaseService
from researchmate.services.vector_store import KnowledgeVectorStore


def _service(tmp_path: Path) -> KnowledgeBaseService:
    settings = Settings(
        RESEARCH_AGENT_TOKEN=SecretStr("x" * 32),
        CHROMA_DIR=tmp_path / "chroma",
        EMBEDDING_BACKEND="hashing",
    )
    return KnowledgeBaseService(
        settings=settings,
        store=KnowledgeVectorStore(persist_directory=tmp_path / "chroma"),
        embedder=HashingEmbeddingBackend(),
    )


def test_ingest_document_rejects_same_paper_id_different_source(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("Methods\nFirst source text.", encoding="utf-8")
    second.write_text("Methods\nSecond source text.", encoding="utf-8")

    service.ingest_document(first, paper_id="shared_doc")

    with pytest.raises(ValueError, match="different source_path"):
        service.ingest_document(second, paper_id="shared_doc")
