from __future__ import annotations

import importlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.adk.events import Event
from google.adk.memory import BaseMemoryService
from google.adk.memory.base_memory_service import SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.sessions import Session
from google.genai import types

from researchmate.config import Settings, get_settings
from researchmate.services.documents import MetadataValue, normalize_text, sanitize_metadata
from researchmate.services.embeddings import (
    EmbeddingBackend,
    LexicalReranker,
    create_embedding_backend,
)

MemoryCategory = str

MEMORY_CATEGORIES: tuple[MemoryCategory, ...] = (
    "research_direction",
    "advisor_requirements",
    "writing_style",
    "recent_tasks",
)

_CATEGORY_KEYWORDS: tuple[tuple[MemoryCategory, tuple[str, ...]], ...] = (
    (
        "research_direction",
        ("研究方向", "研究主题", "课题", "方向", "research direction", "research topic", "focus"),
    ),
    (
        "advisor_requirements",
        ("导师", "老师要求", "advisor", "supervisor", "requirement", "要求"),
    ),
    (
        "writing_style",
        ("写作", "风格", "偏好", "格式", "引用格式", "writing", "style", "preference"),
    ),
    (
        "recent_tasks",
        ("任务", "todo", "deadline", "周报", "计划", "进展", "task"),
    ),
)
_REMEMBER_RE = re.compile(r"^(?:请)?(?:帮我)?记住[:：,，]?\s*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    id: str
    user_id: str
    category: MemoryCategory
    content: str
    created_at: str
    expires_at: str | None = None
    updated_at: str | None = None
    source: str = "manual"
    origin_session_id: str = ""
    score: float | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "category": self.category,
            "content": self.content,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "origin_session_id": self.origin_session_id,
            "score": self.score,
        }


def _load_chromadb() -> Any:
    return importlib.import_module("chromadb")


def _load_chromadb_config() -> Any:
    return importlib.import_module("chromadb.config")


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_expired(expires_at: str | None, *, now: datetime | None = None) -> bool:
    expires = _parse_datetime(expires_at)
    if expires is None:
        return False
    current = now or datetime.now(UTC)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires <= current


def _build_where(filters: dict[str, MetadataValue] | None) -> dict[str, Any] | None:
    if not filters:
        return None
    clauses = [{key: value} for key, value in filters.items() if value not in ("", None)]
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _record_from_chroma(
    *,
    record_id: str,
    document: str,
    metadata: Mapping[str, object],
    score: float | None = None,
) -> MemoryRecord:
    expires_raw = metadata.get("expires_at")
    updated_raw = metadata.get("updated_at")
    return MemoryRecord(
        id=record_id,
        user_id=str(metadata.get("user_id", "")),
        category=str(metadata.get("category", "recent_tasks")),
        content=document,
        created_at=str(metadata.get("created_at", "")),
        expires_at=str(expires_raw) if expires_raw else None,
        updated_at=str(updated_raw) if updated_raw else None,
        source=str(metadata.get("source", "manual")),
        origin_session_id=str(metadata.get("origin_session_id", "")),
        score=score,
    )


def _event_text(event: Event) -> str:
    if not event.content or not event.content.parts:
        return ""
    parts: list[str] = []
    for part in event.content.parts:
        text = getattr(part, "text", None)
        if text:
            parts.append(str(text))
    return normalize_text(" ".join(parts))


def _content_to_text(content: types.Content) -> str:
    parts: list[str] = []
    for part in content.parts or []:
        text = getattr(part, "text", None)
        if text:
            parts.append(str(text))
    return normalize_text(" ".join(parts))


def _infer_category(text: str) -> MemoryCategory | None:
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword.lower() in lowered for keyword in keywords):
            return category
    return None


def _extract_session_facts(session: Session, *, max_facts: int) -> list[tuple[MemoryCategory, str]]:
    facts: list[tuple[MemoryCategory, str]] = []
    seen: set[str] = set()
    for event in session.events:
        if event.author not in {None, "user"}:
            continue
        text = _event_text(event)
        if not text:
            continue
        category = _infer_category(text)
        if category is None and "记住" not in text:
            continue
        category = category or "recent_tasks"
        fact = normalize_text(_REMEMBER_RE.sub("", text))
        key = f"{category}:{fact.lower()}"
        if fact and key not in seen:
            facts.append((category, fact))
            seen.add(key)
        if len(facts) >= max_facts:
            break
    return facts


class ResearchMemoryService(BaseMemoryService):
    """Chroma-backed long-term memory service."""

    def __init__(
        self,
        *,
        persist_directory: str | Path,
        collection_name: str = "memory_records",
        embedding_backend: EmbeddingBackend | None = None,
        max_session_facts: int = 8,
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
        self._embedder = embedding_backend or create_embedding_backend()
        self._max_session_facts = max_session_facts

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ResearchMemoryService:
        settings = settings or get_settings()
        return cls(
            persist_directory=settings.chroma_dir,
            collection_name=settings.memory_collection,
            embedding_backend=create_embedding_backend(settings),
            max_session_facts=settings.memory_max_session_facts,
        )

    def add_record(
        self,
        *,
        user_id: str,
        category: MemoryCategory,
        content: str,
        expires_at: str | None = None,
        record_id: str | None = None,
        source: str = "manual",
        origin_session_id: str = "",
    ) -> MemoryRecord:
        clean_user_id = user_id.strip()
        clean_content = normalize_text(content)
        clean_category = self._validate_category(category)
        if not clean_user_id:
            msg = "user_id must not be empty"
            raise ValueError(msg)
        if not clean_content:
            msg = "content must not be empty"
            raise ValueError(msg)
        if expires_at and _parse_datetime(expires_at) is None:
            msg = "expires_at must be ISO 8601 when provided"
            raise ValueError(msg)

        duplicate = self._find_exact_duplicate(
            user_id=clean_user_id,
            category=clean_category,
            content=clean_content,
        )
        if duplicate is not None and record_id is None:
            return duplicate

        now = _utcnow_iso()
        memory_id = record_id or str(uuid.uuid4())
        metadata = sanitize_metadata(
            {
                "user_id": clean_user_id,
                "category": clean_category,
                "created_at": duplicate.created_at if duplicate else now,
                "updated_at": now if duplicate else "",
                "expires_at": expires_at or "",
                "source": source,
                "origin_session_id": origin_session_id,
            }
        )
        embeddings = self._embedder.encode([clean_content])
        self._collection.upsert(
            ids=[memory_id],
            documents=[clean_content],
            embeddings=embeddings,
            metadatas=[metadata],
        )
        return _record_from_chroma(
            record_id=memory_id,
            document=clean_content,
            metadata=metadata,
        )

    def list_records(
        self,
        *,
        user_id: str | None = None,
        category: MemoryCategory | None = None,
        include_expired: bool = False,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        filters: dict[str, MetadataValue] = {}
        if user_id:
            filters["user_id"] = user_id
        if category:
            filters["category"] = self._validate_category(category)
        kwargs: dict[str, Any] = {"include": ["documents", "metadatas"]}
        where = _build_where(filters)
        if where:
            kwargs["where"] = where
        if limit is not None:
            kwargs["limit"] = limit
        result = self._collection.get(**kwargs)
        records = self._records_from_get_result(result)
        if not include_expired:
            records = [record for record in records if not _is_expired(record.expires_at)]
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        result = self._collection.get(ids=[memory_id], include=["documents", "metadatas"])
        records = self._records_from_get_result(result)
        if not records:
            return None
        record = records[0]
        if _is_expired(record.expires_at):
            return None
        return record

    def update_record(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        category: MemoryCategory | None = None,
        expires_at: str | None = None,
    ) -> MemoryRecord:
        existing = self.get_record(memory_id)
        if existing is None:
            msg = f"memory not found: {memory_id}"
            raise KeyError(msg)
        return self.add_record(
            user_id=existing.user_id,
            category=category or existing.category,
            content=content or existing.content,
            expires_at=expires_at if expires_at is not None else existing.expires_at,
            record_id=memory_id,
            source=existing.source,
            origin_session_id=existing.origin_session_id,
        )

    def delete_record(self, memory_id: str) -> bool:
        if self.get_record(memory_id) is None:
            return False
        self._collection.delete(ids=[memory_id])
        return True

    def search_records(
        self,
        *,
        query: str,
        user_id: str,
        category: MemoryCategory | None = None,
        top_k: int = 5,
    ) -> list[MemoryRecord]:
        self.expire_sweep()
        clean_query = query.strip()
        safe_top_k = min(max(int(top_k), 1), 20)
        filters: dict[str, MetadataValue] = {"user_id": user_id}
        if category:
            filters["category"] = self._validate_category(category)
        if not clean_query:
            return self.list_records(user_id=user_id, category=category, limit=safe_top_k)
        try:
            result = self._collection.query(
                query_embeddings=self._embedder.encode([clean_query]),
                n_results=safe_top_k,
                where=_build_where(filters),
                include=["documents", "metadatas", "distances"],
            )
            records = self._records_from_query_result(result)
        except Exception:
            records = self._lexical_search(
                query=clean_query,
                user_id=user_id,
                category=category,
                top_k=safe_top_k,
            )
        return [record for record in records if not _is_expired(record.expires_at)][:safe_top_k]

    def expire_sweep(self) -> int:
        expired = [
            record
            for record in self.list_records(include_expired=True)
            if _is_expired(record.expires_at)
        ]
        if expired:
            self._collection.delete(ids=[record.id for record in expired])
        return len(expired)

    def has_session_archive(self, session_id: str) -> bool:
        if not session_id:
            return False
        result = self._collection.get(
            where={"origin_session_id": session_id},
            include=[],
            limit=1,
        )
        return bool(result.get("ids", []))

    async def archive_session(self, session: Session) -> int:
        before = len(self.list_records(user_id=session.user_id, include_expired=True))
        await self.add_session_to_memory(session)
        after = len(self.list_records(user_id=session.user_id, include_expired=True))
        return max(after - before, 0)

    async def add_session_to_memory(self, session: Session) -> None:
        if self.has_session_archive(session.id):
            return
        for category, content in _extract_session_facts(
            session,
            max_facts=self._max_session_facts,
        ):
            self.add_record(
                user_id=session.user_id,
                category=category,
                content=content,
                source="session",
                origin_session_id=session.id,
            )

    async def add_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        memories: Sequence[MemoryEntry],
        custom_metadata: Mapping[str, object] | None = None,
    ) -> None:
        del app_name
        metadata = custom_metadata or {}
        default_category = str(metadata.get("category", "recent_tasks"))
        expires_at = metadata.get("expires_at")
        for memory in memories:
            category = str(memory.custom_metadata.get("category", default_category))
            self.add_record(
                user_id=user_id,
                category=category,
                content=_content_to_text(memory.content),
                expires_at=str(expires_at) if expires_at else None,
                source=str(memory.custom_metadata.get("source", "direct")),
            )

    async def search_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        query: str,
    ) -> SearchMemoryResponse:
        del app_name
        records = self.search_records(query=query, user_id=user_id, top_k=5)
        return SearchMemoryResponse(
            memories=[
                MemoryEntry(
                    id=record.id,
                    content=types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=record.content)],
                    ),
                    custom_metadata=record.to_payload(),
                    timestamp=record.created_at,
                )
                for record in records
            ]
        )

    def _find_exact_duplicate(
        self,
        *,
        user_id: str,
        category: MemoryCategory,
        content: str,
    ) -> MemoryRecord | None:
        normalized = content.lower()
        for record in self.list_records(user_id=user_id, category=category):
            if record.content.lower() == normalized:
                return record
        return None

    def _lexical_search(
        self,
        *,
        query: str,
        user_id: str,
        category: MemoryCategory | None,
        top_k: int,
    ) -> list[MemoryRecord]:
        records = self.list_records(user_id=user_id, category=category)
        scorer = LexicalReranker()
        scores = scorer.score(query, [record.content for record in records])
        scored = [
            MemoryRecord(
                id=record.id,
                user_id=record.user_id,
                category=record.category,
                content=record.content,
                created_at=record.created_at,
                expires_at=record.expires_at,
                updated_at=record.updated_at,
                source=record.source,
                origin_session_id=record.origin_session_id,
                score=float(score),
            )
            for record, score in zip(records, scores, strict=True)
            if score > 0.0
        ]
        scored.sort(key=lambda item: item.score or 0.0, reverse=True)
        return scored[:top_k]

    def _records_from_get_result(self, result: Mapping[str, Any]) -> list[MemoryRecord]:
        ids = result.get("ids", [])
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        records: list[MemoryRecord] = []
        for index, record_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            document = documents[index] if index < len(documents) else ""
            records.append(
                _record_from_chroma(
                    record_id=str(record_id),
                    document=str(document),
                    metadata=metadata if isinstance(metadata, Mapping) else {},
                )
            )
        return records

    def _records_from_query_result(self, result: Mapping[str, Any]) -> list[MemoryRecord]:
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        records: list[MemoryRecord] = []
        for index, record_id in enumerate(ids):
            distance = float(distances[index]) if index < len(distances) else 0.0
            score = 1.0 / (1.0 + max(distance, 0.0))
            metadata = metadatas[index] if index < len(metadatas) else {}
            document = documents[index] if index < len(documents) else ""
            records.append(
                _record_from_chroma(
                    record_id=str(record_id),
                    document=str(document),
                    metadata=metadata if isinstance(metadata, Mapping) else {},
                    score=score,
                )
            )
        return records

    def _validate_category(self, category: str) -> MemoryCategory:
        clean = category.strip()
        if clean not in MEMORY_CATEGORIES:
            msg = f"category must be one of: {', '.join(MEMORY_CATEGORIES)}"
            raise ValueError(msg)
        return clean
