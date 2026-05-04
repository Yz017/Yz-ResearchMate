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
