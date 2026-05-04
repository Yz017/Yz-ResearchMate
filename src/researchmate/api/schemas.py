from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    code: str
    message: str
    trace_id: str
    retryable: bool = False


class DependencyStatus(BaseModel):
    ok: bool
    detail: str


class LivezResponse(BaseModel):
    status: str
    version: str


class ReadyzResponse(BaseModel):
    status: str
    version: str
    dependencies: dict[str, DependencyStatus]
    runtime: dict[str, Any]


class LlmStatus(BaseModel):
    ok: bool
    cached: bool
    checked_at: datetime | None = None
    detail: str | None = None


class HealthResponse(ReadyzResponse):
    llm: LlmStatus | None = None


class VersionResponse(BaseModel):
    version: str
    git_sha: str
    adk_version: str
    model: str
    runtime: dict[str, Any]


class SessionCreateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str | None = None
    state: dict[str, Any] | None = None


class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    app_name: str
    created_at: datetime
    last_update_time: datetime
    event_count: int
    state: dict[str, Any] = Field(default_factory=dict)


class SessionDeleteResponse(BaseModel):
    session_id: str
    deleted: bool


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    attachments: list[str] = Field(default_factory=list)


class MemoryCreateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    content: str = Field(min_length=1)
    expires_at: datetime | None = None


class MemoryUpdateRequest(BaseModel):
    category: str | None = None
    content: str | None = None
    expires_at: datetime | None = None


class MemoryResponse(BaseModel):
    id: str
    user_id: str
    category: str
    content: str
    created_at: datetime
    expires_at: datetime | None = None
    updated_at: datetime | None = None
    source: str
    origin_session_id: str = ""
    score: float | None = None


class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]
    count: int


class MemoryDeleteResponse(BaseModel):
    memory_id: str
    deleted: bool


class MemoryArchiveRequest(BaseModel):
    session_id: str = Field(min_length=1)


class MemoryArchiveResponse(BaseModel):
    session_id: str
    archived_count: int


class KnowledgeIngestRequest(BaseModel):
    oss_keys: list[str] = Field(min_length=1)
    owner_user_id: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    paper_id: str | None = None
    title: str | None = None


class JobSubmitResponse(BaseModel):
    job_id: str


class JobResponse(BaseModel):
    id: str
    kind: str
    state: str
    progress: float
    error: str | None = None
    params: dict[str, Any]
    result: dict[str, Any] | None = None
    user_id: str
    created_at: datetime
    finished_at: datetime | None = None


class KnowledgeDocumentResponse(BaseModel):
    doc_id: str
    title: str
    source_path: str
    oss_key: str
    user_id: str
    tags: list[str]
    chunks: int
    pages: list[int]
    ingested_at: datetime | None = None


class KnowledgeDocumentListResponse(BaseModel):
    items: list[KnowledgeDocumentResponse]
    count: int


class KnowledgeDocumentDeleteResponse(BaseModel):
    doc_id: str
    deleted_chunks: int
