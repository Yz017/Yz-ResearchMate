from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from researchmate.config import Settings, get_settings
from researchmate.services.knowledge_base import IngestedDocument

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_TAG_SEPARATOR_RE = re.compile(r"[,;]\s*")


@dataclass(frozen=True, slots=True)
class PaperRecord:
    id: str
    title: str
    user_id: str
    arxiv_id: str = ""
    doi: str = ""
    authors: list[str] | None = None
    venue: str = ""
    year: int | None = None
    tags: list[str] | None = None
    read_at: str | None = None
    rating: float | None = None
    oss_path: str = ""
    created_at: str = ""
    updated_at: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "arxiv_id": self.arxiv_id,
            "doi": self.doi,
            "title": self.title,
            "authors": self.authors or [],
            "venue": self.venue,
            "year": self.year,
            "tags": self.tags or [],
            "read_at": self.read_at,
            "rating": self.rating,
            "oss_path": self.oss_path,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _stable_id(*parts: str) -> str:
    seed = "\n".join(part.strip().lower() for part in parts if part and part.strip())
    if not seed:
        return str(uuid.uuid4())
    return uuid.uuid5(uuid.NAMESPACE_URL, seed).hex


def _clean_tags(tags: Sequence[str] | str | None) -> list[str]:
    if tags is None:
        return []
    raw: Sequence[str] = _TAG_SEPARATOR_RE.split(tags) if isinstance(tags, str) else tags
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw:
        tag = str(item).strip()
        if tag and tag not in seen:
            cleaned.append(tag)
            seen.add(tag)
    return cleaned


def _decode_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _row_to_record(row: sqlite3.Row) -> PaperRecord:
    return PaperRecord(
        id=str(row["id"]),
        arxiv_id=str(row["arxiv_id"] or ""),
        doi=str(row["doi"] or ""),
        title=str(row["title"]),
        authors=_decode_list(row["authors_json"]),
        venue=str(row["venue"] or ""),
        year=int(row["year"]) if row["year"] is not None else None,
        tags=_decode_list(row["tags_json"]),
        read_at=str(row["read_at"]) if row["read_at"] else None,
        rating=float(row["rating"]) if row["rating"] is not None else None,
        oss_path=str(row["oss_path"] or ""),
        user_id=str(row["user_id"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]) if row["updated_at"] else None,
    )


def infer_year(*values: object) -> int | None:
    for value in values:
        if value is None:
            continue
        match = _YEAR_RE.search(str(value))
        if match:
            return int(match.group(0))
    return None


class PaperRepository:
    """SQLite repository for paper metadata used by tasks and the API."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> PaperRepository:
        settings = settings or get_settings()
        return cls(settings.papers_db_path)

    def upsert_paper(
        self,
        *,
        title: str,
        user_id: str,
        paper_id: str | None = None,
        arxiv_id: str = "",
        doi: str = "",
        authors: Sequence[str] | None = None,
        venue: str = "",
        year: int | None = None,
        tags: Sequence[str] | str | None = None,
        read_at: str | None = None,
        rating: float | None = None,
        oss_path: str = "",
    ) -> PaperRecord:
        clean_title = title.strip() or paper_id or arxiv_id or doi or "Untitled paper"
        resolved_id = paper_id or _stable_id(user_id, arxiv_id, doi, clean_title, oss_path)
        now = _utcnow_iso()
        clean_authors = [str(author).strip() for author in authors or () if str(author).strip()]
        clean_tags = _clean_tags(tags)
        with self._connect() as db:
            db.execute(
                """
                insert into papers (
                    id, arxiv_id, doi, title, authors_json, venue, year, tags_json,
                    read_at, rating, oss_path, user_id, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    arxiv_id = excluded.arxiv_id,
                    doi = excluded.doi,
                    title = excluded.title,
                    authors_json = excluded.authors_json,
                    venue = excluded.venue,
                    year = excluded.year,
                    tags_json = excluded.tags_json,
                    read_at = coalesce(excluded.read_at, papers.read_at),
                    rating = coalesce(excluded.rating, papers.rating),
                    oss_path = excluded.oss_path,
                    user_id = excluded.user_id,
                    updated_at = excluded.updated_at
                """,
                (
                    resolved_id,
                    arxiv_id,
                    doi,
                    clean_title,
                    json.dumps(clean_authors, ensure_ascii=False),
                    venue,
                    year,
                    json.dumps(clean_tags, ensure_ascii=False),
                    read_at,
                    rating,
                    oss_path,
                    user_id,
                    now,
                    now,
                ),
            )
            db.commit()
        record = self.get_paper(resolved_id)
        if record is None:
            msg = f"failed to read upserted paper: {resolved_id}"
            raise RuntimeError(msg)
        return record

    def upsert_ingested_document(self, document: IngestedDocument) -> PaperRecord:
        return self.upsert_paper(
            paper_id=document.doc_id,
            title=document.title,
            user_id=document.user_id,
            tags=document.tags,
            oss_path=document.oss_key,
            year=infer_year(document.title, document.oss_key, document.source_path),
        )

    def get_paper(self, paper_id: str) -> PaperRecord | None:
        with self._connect() as db:
            row = db.execute("select * from papers where id = ?", (paper_id,)).fetchone()
        return _row_to_record(row) if row is not None else None

    def list_papers(
        self,
        *,
        user_id: str | None = None,
        tag: str | None = None,
        year: int | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PaperRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if year is not None:
            clauses.append("year = ?")
            params.append(year)
        if q:
            clauses.append("(title like ? or venue like ? or authors_json like ?)")
            like = f"%{q}%"
            params.extend([like, like, like])
        sql = "select * from papers"
        if clauses:
            sql += " where " + " and ".join(clauses)
        sql += " order by coalesce(read_at, updated_at, created_at) desc limit ? offset ?"
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        records = [_row_to_record(row) for row in rows]
        if tag:
            records = [record for record in records if tag in (record.tags or [])]
        return records

    def update_paper(
        self,
        paper_id: str,
        *,
        tags: Sequence[str] | str | None = None,
        read_at: str | None = None,
        rating: float | None = None,
    ) -> PaperRecord:
        current = self.get_paper(paper_id)
        if current is None:
            msg = f"paper not found: {paper_id}"
            raise KeyError(msg)
        resolved_tags = current.tags or []
        if tags is not None:
            resolved_tags = _clean_tags(tags)
        resolved_read_at = current.read_at if read_at is None else read_at
        resolved_rating = current.rating if rating is None else rating
        with self._connect() as db:
            db.execute(
                """
                update papers
                set tags_json = ?, read_at = ?, rating = ?, updated_at = ?
                where id = ?
                """,
                (
                    json.dumps(resolved_tags, ensure_ascii=False),
                    resolved_read_at,
                    resolved_rating,
                    _utcnow_iso(),
                    paper_id,
                ),
            )
            db.commit()
        updated = self.get_paper(paper_id)
        if updated is None:
            msg = f"paper not found after update: {paper_id}"
            raise KeyError(msg)
        return updated

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                create table if not exists papers (
                    id text primary key,
                    arxiv_id text not null default '',
                    doi text not null default '',
                    title text not null,
                    authors_json text not null default '[]',
                    venue text not null default '',
                    year integer,
                    tags_json text not null default '[]',
                    read_at text,
                    rating real,
                    oss_path text not null default '',
                    user_id text not null,
                    created_at text not null,
                    updated_at text
                )
                """
            )
            db.execute("create index if not exists idx_papers_user on papers(user_id)")
            db.execute("create index if not exists idx_papers_year on papers(year)")
            db.commit()
