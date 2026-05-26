from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from researchmate.config import Settings, get_settings
from researchmate.services.documents import MetadataValue, RetrievedChunk, infer_paper_id
from researchmate.services.embeddings import EmbeddingBackend, create_embedding_backend
from researchmate.services.parsers import parse_document_to_chunks
from researchmate.services.vector_store import KnowledgeVectorStore

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class IngestedDocument:
    doc_id: str
    title: str
    source_path: str
    oss_key: str
    user_id: str
    tags: list[str]
    chunks: int
    pages: list[int]
    ingested_at: str

    def to_payload(self) -> dict[str, object]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "source_path": self.source_path,
            "oss_key": self.oss_key,
            "user_id": self.user_id,
            "tags": self.tags,
            "chunks": self.chunks,
            "pages": self.pages,
            "ingested_at": self.ingested_at,
        }


def _batched(items: Sequence[_T], batch_size: int) -> Iterable[Sequence[_T]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def _split_tags(value: object) -> list[str]:
    if not isinstance(value, str) or not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


class KnowledgeBaseService:
    """Knowledge-base operations shared by scripts, API jobs, and CLI tests."""

    def __init__(
        self,
        *,
        settings: Settings,
        store: KnowledgeVectorStore | None = None,
        embedder: EmbeddingBackend | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or KnowledgeVectorStore.from_settings(settings)
        self.embedder = embedder or create_embedding_backend(settings)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> KnowledgeBaseService:
        return cls(settings=settings or get_settings())

    def ingest_document(
        self,
        path: str | Path,
        *,
        paper_id: str | None = None,
        title: str | None = None,
        oss_key: str = "",
        user_id: str = "",
        tags: Sequence[str] | None = None,
        ingested_at: str | None = None,
    ) -> IngestedDocument:
        clean_tags = [tag.strip() for tag in tags or () if tag.strip()]
        timestamp = ingested_at or datetime.now(UTC).isoformat()
        source_path = str(Path(path))
        resolved_paper_id = paper_id or infer_paper_id(path)
        existing = self.store.list_chunks(filters={"paper_id": resolved_paper_id})
        source_paths = {
            str(chunk.metadata.get("source_path", ""))
            for chunk in existing
            if str(chunk.metadata.get("source_path", ""))
        }
        if source_paths and source_paths != {source_path}:
            msg = (
                f"paper_id {resolved_paper_id} already exists for a different source_path; "
                "use --paper-id to override or delete the existing document first"
            )
            raise ValueError(msg)
        chunks = parse_document_to_chunks(
            path,
            paper_id=paper_id,
            title=title,
            oss_key=oss_key,
            user_id=user_id,
            tags=clean_tags,
            ingested_at=timestamp,
        )
        existing_ids = self.store.get_existing_ids([chunk.id for chunk in chunks])
        inserted_ids: list[str] = []
        try:
            for batch in _batched(chunks, self.settings.embedding_batch_size):
                embeddings = self.embedder.encode([chunk.text for chunk in batch])
                self.store.upsert_chunks(batch, embeddings, embedding_model=self.embedder.model_id)
                inserted_ids.extend(chunk.id for chunk in batch if chunk.id not in existing_ids)
        except Exception:
            self.store.delete_ids(inserted_ids)
            raise

        resolved_doc_id = chunks[0].paper_id if chunks else (paper_id or Path(path).stem)
        resolved_title = chunks[0].title if chunks else (title or Path(path).stem)
        pages = sorted({int(chunk.page) for chunk in chunks})
        return IngestedDocument(
            doc_id=resolved_doc_id,
            title=resolved_title,
            source_path=str(path),
            oss_key=oss_key,
            user_id=user_id,
            tags=clean_tags,
            chunks=len(chunks),
            pages=pages,
            ingested_at=timestamp,
        )

    def list_documents(
        self,
        *,
        user_id: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IngestedDocument]:
        filters: dict[str, MetadataValue] = {}
        if user_id:
            filters["user_id"] = user_id
        chunks = self.store.list_chunks(filters=filters or None)
        grouped: dict[str, list[RetrievedChunk]] = {}
        for chunk in chunks:
            tags = _split_tags(chunk.metadata.get("tags", ""))
            if tag and tag not in tags:
                continue
            grouped.setdefault(chunk.paper_id, []).append(chunk)

        documents: list[IngestedDocument] = []
        for doc_id, doc_chunks in grouped.items():
            first = doc_chunks[0]
            tags_seen: set[str] = set()
            for chunk in doc_chunks:
                tags_seen.update(_split_tags(chunk.metadata.get("tags", "")))
            pages = sorted(
                {
                    int(chunk.metadata["page"])
                    for chunk in doc_chunks
                    if isinstance(chunk.metadata.get("page"), int)
                }
            )
            ingested_values = [
                str(chunk.metadata.get("ingested_at", ""))
                for chunk in doc_chunks
                if chunk.metadata.get("ingested_at")
            ]
            documents.append(
                IngestedDocument(
                    doc_id=doc_id,
                    title=first.title,
                    source_path=str(first.metadata.get("source_path", "")),
                    oss_key=str(first.metadata.get("oss_key", "")),
                    user_id=str(first.metadata.get("user_id", "")),
                    tags=sorted(tags_seen),
                    chunks=len(doc_chunks),
                    pages=pages,
                    ingested_at=max(ingested_values) if ingested_values else "",
                )
            )
        documents.sort(key=lambda item: item.ingested_at, reverse=True)
        return documents[offset : offset + limit]

    def delete_document(self, doc_id: str) -> int:
        chunks = self.store.list_chunks(filters={"paper_id": doc_id})
        self.store.delete_where({"paper_id": doc_id})
        return len(chunks)

    ingest_pdf = ingest_document
