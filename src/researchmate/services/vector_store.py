from __future__ import annotations

import importlib
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from researchmate.config import Settings, get_settings
from researchmate.services.documents import (
    KnowledgeChunk,
    MetadataValue,
    RetrievedChunk,
    sanitize_metadata,
)


def _load_chromadb() -> Any:
    return importlib.import_module("chromadb")


def _load_chromadb_config() -> Any:
    return importlib.import_module("chromadb.config")


def _build_where(filters: dict[str, MetadataValue] | None) -> dict[str, Any] | None:
    if not filters:
        return None
    clauses = [{key: value} for key, value in filters.items() if value not in ("", None)]
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _metadata_matches(
    metadata: dict[str, MetadataValue],
    filters: dict[str, MetadataValue] | None,
) -> bool:
    if not filters:
        return True
    for key, value in filters.items():
        if value in ("", None):
            continue
        if metadata.get(key) != value:
            return False
    return True


class KnowledgeVectorStore:
    """Thin Chroma wrapper for the local knowledge-base collection."""

    def __init__(
        self,
        *,
        persist_directory: str | Path,
        collection_name: str = "kb_chunks",
    ) -> None:
        self.persist_directory = Path(persist_directory)
        self.collection_name = collection_name
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        chromadb = _load_chromadb()
        config = _load_chromadb_config()
        settings = config.Settings(anonymized_telemetry=False)
        self._client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=settings,
        )
        self._collection = self._client.get_or_create_collection(name=collection_name)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> KnowledgeVectorStore:
        settings = settings or get_settings()
        return cls(
            persist_directory=settings.chroma_dir,
            collection_name=settings.kb_collection,
        )

    @property
    def collection(self) -> Any:
        return self._collection

    def reset(self) -> None:
        with suppress(Exception):
            self._client.delete_collection(self.collection_name)
        self._collection = self._client.get_or_create_collection(name=self.collection_name)

    def count(self) -> int:
        return int(self._collection.count())

    def upsert_chunks(
        self,
        chunks: Sequence[KnowledgeChunk],
        embeddings: Sequence[Sequence[float]],
        *,
        embedding_model: str,
    ) -> int:
        if len(chunks) != len(embeddings):
            msg = "chunks and embeddings must have the same length"
            raise ValueError(msg)
        if not chunks:
            return 0
        ids = [chunk.id for chunk in chunks]
        documents = [chunk.text for chunk in chunks]
        metadatas = [
            sanitize_metadata(chunk.metadata(embedding_model=embedding_model)) for chunk in chunks
        ]
        self._collection.upsert(
            ids=ids,
            embeddings=[list(map(float, embedding)) for embedding in embeddings],
            documents=documents,
            metadatas=metadatas,
        )
        return len(chunks)

    def delete_ids(self, ids: Sequence[str]) -> None:
        if ids:
            self._collection.delete(ids=list(ids))

    def get_existing_ids(self, ids: Sequence[str]) -> set[str]:
        if not ids:
            return set()
        result = self._collection.get(ids=list(ids), include=[])
        return {str(chunk_id) for chunk_id in result.get("ids", [])}

    def query_dense(
        self,
        embedding: Sequence[float],
        *,
        top_k: int,
        filters: dict[str, MetadataValue] | None = None,
    ) -> list[RetrievedChunk]:
        if self.count() == 0:
            return []
        result = self._collection.query(
            query_embeddings=[list(map(float, embedding))],
            n_results=top_k,
            where=_build_where(filters),
            include=["documents", "metadatas", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        retrieved: list[RetrievedChunk] = []
        for index, chunk_id in enumerate(ids):
            metadata = sanitize_metadata(metadatas[index] if index < len(metadatas) else {})
            if not _metadata_matches(metadata, filters):
                continue
            distance = float(distances[index]) if index < len(distances) else 0.0
            score = 1.0 / (1.0 + max(distance, 0.0))
            retrieved.append(
                RetrievedChunk(
                    id=str(chunk_id),
                    text=str(documents[index]),
                    metadata=metadata,
                    score=score,
                    dense_rank=index + 1,
                )
            )
        return retrieved

    def list_chunks(
        self,
        *,
        filters: dict[str, MetadataValue] | None = None,
        limit: int | None = None,
    ) -> list[RetrievedChunk]:
        if self.count() == 0:
            return []
        kwargs: dict[str, Any] = {
            "include": ["documents", "metadatas"],
            "where": _build_where(filters),
        }
        if limit is not None:
            kwargs["limit"] = limit
        result = self._collection.get(**kwargs)
        ids = result.get("ids", [])
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        chunks: list[RetrievedChunk] = []
        for index, chunk_id in enumerate(ids):
            metadata = sanitize_metadata(metadatas[index] if index < len(metadatas) else {})
            if not _metadata_matches(metadata, filters):
                continue
            chunks.append(
                RetrievedChunk(
                    id=str(chunk_id),
                    text=str(documents[index]),
                    metadata=metadata,
                    score=0.0,
                )
            )
        return chunks
