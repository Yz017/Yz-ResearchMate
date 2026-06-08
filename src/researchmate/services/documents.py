from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MetadataValue = str | int | float | bool

_PAPER_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ParsedPage:
    """Text extracted from one logical document page."""

    page_number: int
    text: str
    ocr: bool = False


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """A chunk ready for embedding and vector storage."""

    id: str
    text: str
    paper_id: str
    title: str
    page: int
    section: str
    source_path: str
    oss_key: str
    chunk_index: int
    chunk_hash: str
    ocr: bool = False
    owner_user_id: str = ""
    tags: tuple[str, ...] = ()
    ingested_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        text: str,
        paper_id: str,
        title: str,
        page: int,
        section: str,
        source_path: str,
        oss_key: str = "",
        chunk_index: int,
        ocr: bool = False,
        owner_user_id: str = "",
        tags: tuple[str, ...] = (),
        ingested_at: str = "",
    ) -> KnowledgeChunk:
        normalized_text = normalize_text(text)
        chunk_hash = stable_text_hash("\n".join([paper_id, str(page), section, normalized_text]))
        return cls(
            id=f"{paper_id}:{chunk_hash}",
            text=normalized_text,
            paper_id=paper_id,
            title=title,
            page=page,
            section=section,
            source_path=source_path,
            oss_key=oss_key,
            chunk_index=chunk_index,
            chunk_hash=chunk_hash,
            ocr=ocr,
            owner_user_id=owner_user_id,
            tags=tags,
            ingested_at=ingested_at,
        )

    @property
    def citation(self) -> str:
        return _format_citation(self.paper_id, self.page, self.section)

    def metadata(self, *, embedding_model: str | None = None) -> dict[str, MetadataValue]:
        payload: dict[str, MetadataValue] = {
            "paper_id": self.paper_id,
            "title": self.title,
            "page": self.page,
            "section": self.section,
            "source_path": self.source_path,
            "oss_key": self.oss_key,
            "chunk_index": self.chunk_index,
            "chunk_hash": self.chunk_hash,
            "ocr": self.ocr,
            "citation": self.citation,
            "user_id": self.owner_user_id,
            "tags": ",".join(self.tags),
            "ingested_at": self.ingested_at,
        }
        if embedding_model:
            payload["embedding_model"] = embedding_model
        return payload


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A chunk returned by retrieval and ready for tool serialization."""

    id: str
    text: str
    metadata: dict[str, MetadataValue]
    score: float
    dense_rank: int | None = None
    sparse_rank: int | None = None
    rerank_score: float | None = None

    @property
    def paper_id(self) -> str:
        return str(self.metadata.get("paper_id", "unknown"))

    @property
    def title(self) -> str:
        return str(self.metadata.get("title", self.paper_id))

    @property
    def page(self) -> int | str:
        value = self.metadata.get("page", "?")
        return value if isinstance(value, int) else str(value)

    @property
    def section(self) -> str:
        return str(self.metadata.get("section", "unknown"))

    @property
    def citation(self) -> str:
        value = self.metadata.get("citation")
        if isinstance(value, str) and value:
            return value
        section = self.section
        page = self.page
        if isinstance(page, int):
            return _format_citation(self.paper_id, page, section)
        return f"[source: {self.paper_id}, p.{page}]"

    def to_tool_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "paper_id": self.paper_id,
            "title": self.title,
            "page": self.page,
            "section": self.section,
            "citation": self.citation,
            "score": round(self.score, 6),
            "dense_rank": self.dense_rank,
            "sparse_rank": self.sparse_rank,
            "rerank_score": None if self.rerank_score is None else round(self.rerank_score, 6),
            "text": self.text,
            "source_path": str(self.metadata.get("source_path", "")),
            "oss_key": str(self.metadata.get("oss_key", "")),
        }


def normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _format_citation(paper_id: str, page: int, section: str) -> str:
    clean_section = normalize_text(section)
    if page <= 1 and clean_section and clean_section.lower() != "unknown":
        return f"[source: {paper_id} · {clean_section}]"
    return f"[source: {paper_id}, p.{page}]"


def infer_paper_id(path: str | Path) -> str:
    stem = Path(path).stem.strip() or "paper"
    paper_id = _PAPER_ID_RE.sub("_", stem).strip("._-")
    return paper_id or "paper"


def stable_text_hash(text: str, *, length: int = 16) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def coerce_metadata(value: Any) -> MetadataValue | None:
    if value is None:
        return None
    if isinstance(value, bool | int | float | str):
        return value
    return str(value)


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, MetadataValue]:
    sanitized: dict[str, MetadataValue] = {}
    for key, value in metadata.items():
        coerced = coerce_metadata(value)
        if coerced is not None:
            sanitized[key] = coerced
    return sanitized
