from __future__ import annotations

import asyncio
import contextvars
import importlib
import importlib.util
import json
import os
import re
import secrets
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import aiosqlite
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService, Session
from google.adk.version import __version__ as adk_version
from google.genai import types
from loguru import logger
from starlette.responses import Response

from researchmate import __version__
from researchmate.agent import root_agent
from researchmate.agents.llm_policy import classify_llm_error
from researchmate.api.schemas import (
    ChatRequest,
    DependencyStatus,
    ErrorResponse,
    HealthResponse,
    JobResponse,
    JobSubmitResponse,
    KnowledgeDocumentDeleteResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentResponse,
    KnowledgeIngestRequest,
    LivezResponse,
    LlmStatus,
    MemoryArchiveRequest,
    MemoryArchiveResponse,
    MemoryCreateRequest,
    MemoryDeleteResponse,
    MemoryListResponse,
    MemoryResponse,
    MemoryUpdateRequest,
    PaperListResponse,
    PaperResponse,
    PaperUpdateRequest,
    ReadyzResponse,
    SessionCreateRequest,
    SessionDeleteResponse,
    SessionResponse,
    TaskKindsResponse,
    TaskRunRequest,
    TaskSubmitResponse,
    VersionResponse,
)
from researchmate.config import Settings, get_settings
from researchmate.services.job_runner import JobContext, JobRecord, JobRunner
from researchmate.services.knowledge_base import IngestedDocument, KnowledgeBaseService
from researchmate.services.memory_service import MemoryRecord, ResearchMemoryService
from researchmate.services.oss_client import OssClient
from researchmate.services.paper_repo import PaperRecord, PaperRepository
from researchmate.services.parsers import UnsupportedFormatError
from researchmate.services.task_kinds import (
    normalize_task_kind,
    register_task_handlers,
    task_kind_schema_payload,
    validate_task_params,
)

APP_NAME = "researchmate"
_CHAT_TIMEOUT_SECONDS = 120.0
_DEEP_HEALTH_TTL_SECONDS = 300.0
_CITATION_RE = re.compile(
    r"\[source:\s*(?P<paper_id>[^,\]·]+?)\s*"
    r"(?:,\s*p\.?\s*(?P<page>\d+)|·\s*(?P<section>[^\]]+?))\]",
    re.IGNORECASE,
)
_THOUGHT_PREFIXES = (
    "/*PLANNING*/",
    "/*REPLANNING*/",
    "/*REASONING*/",
    "/*ACTION*/",
    "/*FINAL_ANSWER*/",
)
_TRACE_ID: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


@dataclass(slots=True)
class _DeepHealthCache:
    expires_at: float = 0.0
    status: LlmStatus | None = None


class _ApiRuntime:
    def __init__(self, settings: Settings) -> None:
        self.session_service = DatabaseSessionService(settings.adk_session_db_url)
        self.memory_service = ResearchMemoryService.from_settings(settings)
        self.runner = Runner(
            app_name=APP_NAME,
            agent=root_agent,
            session_service=self.session_service,
            memory_service=self.memory_service,
            auto_create_session=False,
        )

    async def close(self) -> None:
        await self.runner.close()  # type: ignore[no-untyped-call]
        await self.session_service.close()


_runtime_by_session_uri: dict[str, _ApiRuntime] = {}
_deep_health_cache = _DeepHealthCache()
_deep_health_lock = asyncio.Lock()


def _ensure_runtime_dirs(settings: Settings) -> None:
    settings.session_db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    settings.oss_local_dir.mkdir(parents=True, exist_ok=True)
    settings.oss_cache_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.papers_db_path.parent.mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(parents=True, exist_ok=True)


def _configure_logging() -> None:
    Path("logs").mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        "logs/researchmate.json",
        serialize=True,
        rotation="00:00",
        retention="14 days",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )


def _get_runtime(settings: Settings) -> _ApiRuntime:
    runtime = _runtime_by_session_uri.get(settings.adk_session_db_url)
    if runtime is None:
        runtime = _ApiRuntime(settings)
        _runtime_by_session_uri[settings.adk_session_db_url] = runtime
    return runtime


def _new_uuid7() -> str:
    unix_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (unix_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


def _current_trace_id() -> str:
    return _TRACE_ID.get() or _new_uuid7()


def _error_payload(
    *,
    code: str,
    message: str,
    retryable: bool = False,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return ErrorResponse(
        code=code,
        message=message,
        trace_id=trace_id or _current_trace_id(),
        retryable=retryable,
    ).model_dump()


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    trace_id: str | None = None,
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content=_error_payload(
            code=code,
            message=message,
            retryable=retryable,
            trace_id=trace_id,
        ),
    )
    response.headers["X-Trace-Id"] = trace_id or _current_trace_id()
    return response


def _requires_token(path: str) -> bool:
    public_prefixes = (
        "/docs",
        "/redoc",
        "/openapi.json",
        "/health",
        "/version",
        "/favicon.ico",
    )
    return not any(path == prefix or path.startswith(f"{prefix}/") for prefix in public_prefixes)


def _runtime_info(settings: Settings) -> dict[str, Any]:
    torch_installed = importlib.util.find_spec("torch") is not None
    resolved_device = "cpu" if settings.embedding_device == "auto" else settings.embedding_device
    return {
        "embedding_device": settings.embedding_device,
        "resolved_embedding_device": resolved_device,
        "torch_installed": torch_installed,
        "cuda_available": None,
        "mode": "gpu" if resolved_device == "cuda" else "cpu",
        "device_name": resolved_device,
        "notes": "lightweight API check; run scripts/detect_runtime.py for CUDA probing",
    }


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


async def _check_session_db(settings: Settings) -> DependencyStatus:
    try:
        settings.session_db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(settings.session_db_path) as connection:
            await connection.execute("select 1")
        return DependencyStatus(ok=True, detail=str(settings.session_db_path))
    except Exception as exc:
        return DependencyStatus(ok=False, detail=f"{type(exc).__name__}: {exc}")


def _check_chroma_dir(settings: Settings) -> DependencyStatus:
    try:
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(settings.chroma_dir, os.R_OK | os.W_OK):
            return DependencyStatus(
                ok=False,
                detail=f"{settings.chroma_dir} is not readable/writable",
            )
        return DependencyStatus(ok=True, detail=str(settings.chroma_dir))
    except Exception as exc:
        return DependencyStatus(ok=False, detail=f"{type(exc).__name__}: {exc}")


def _check_writable_dir(path: Path) -> DependencyStatus:
    try:
        path.mkdir(parents=True, exist_ok=True)
        if not os.access(path, os.R_OK | os.W_OK):
            return DependencyStatus(ok=False, detail=f"{path} is not readable/writable")
        return DependencyStatus(ok=True, detail=str(path))
    except Exception as exc:
        return DependencyStatus(ok=False, detail=f"{type(exc).__name__}: {exc}")


async def _readyz_payload(settings: Settings) -> ReadyzResponse:
    dependencies = {
        "config": DependencyStatus(ok=True, detail="loaded"),
        "chroma": _check_chroma_dir(settings),
        "oss": DependencyStatus(
            ok=True,
            detail=(
                f"remote bucket={settings.oss_bucket}"
                if settings.has_oss_credentials
                else f"local fallback {settings.oss_local_dir}"
            ),
        ),
        "cache": _check_writable_dir(settings.oss_cache_dir),
        "jobs_db": _check_writable_dir(settings.jobs_db_path.parent),
        "papers_db": _check_writable_dir(settings.papers_db_path.parent),
        "session_db": await _check_session_db(settings),
    }
    status_text = "ok" if all(item.ok for item in dependencies.values()) else "degraded"
    return ReadyzResponse(
        status=status_text,
        version=__version__,
        dependencies=dependencies,
        runtime=_runtime_info(settings),
    )


async def _probe_llm(settings: Settings, *, force: bool) -> LlmStatus:
    now = time.time()
    if not force and _deep_health_cache.status and now < _deep_health_cache.expires_at:
        cached = _deep_health_cache.status.model_copy(update={"cached": True})
        return cached
    async with _deep_health_lock:
        now = time.time()
        if not force and _deep_health_cache.status and now < _deep_health_cache.expires_at:
            cached = _deep_health_cache.status.model_copy(update={"cached": True})
            return cached
        checked_at = datetime.now(UTC)
        if not settings.has_deepseek_api_key:
            status_payload = LlmStatus(
                ok=False,
                cached=False,
                checked_at=checked_at,
                detail="DEEPSEEK_API_KEY is not configured",
            )
        else:
            models = [settings.researchmate_llm_model, *settings.llm_fallback_models]
            last_error: Exception | None = None
            try:
                litellm = importlib.import_module("litellm")
            except Exception as exc:
                status_payload = LlmStatus(
                    ok=False,
                    cached=False,
                    checked_at=checked_at,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            else:
                for model in models:
                    try:
                        await asyncio.wait_for(
                            litellm.acompletion(
                                model=model,
                                messages=[{"role": "user", "content": "ping"}],
                                max_tokens=1,
                            ),
                            timeout=10.0,
                        )
                    except Exception as exc:
                        last_error = exc
                        continue
                    status_payload = LlmStatus(
                        ok=True,
                        cached=False,
                        checked_at=checked_at,
                        detail=f"ok ({model})",
                    )
                    break
                else:
                    assert last_error is not None
                    status_payload = LlmStatus(
                        ok=False,
                        cached=False,
                        checked_at=checked_at,
                        detail=f"{type(last_error).__name__}: {last_error}",
                    )
        _deep_health_cache.status = status_payload
        _deep_health_cache.expires_at = time.time() + _DEEP_HEALTH_TTL_SECONDS
        return status_payload


async def _find_session(runtime: _ApiRuntime, session_id: str) -> Session:
    sessions = await runtime.session_service.list_sessions(app_name=APP_NAME)
    for session in sessions.sessions:
        if session.id == session_id:
            full_session = await runtime.session_service.get_session(
                app_name=APP_NAME,
                user_id=session.user_id,
                session_id=session_id,
            )
            if full_session is not None:
                return cast(Session, full_session)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")


def _session_response(session: Session) -> SessionResponse:
    timestamp = datetime.fromtimestamp(session.last_update_time, UTC)
    return SessionResponse(
        session_id=session.id,
        user_id=session.user_id,
        app_name=session.app_name,
        created_at=timestamp,
        last_update_time=timestamp,
        event_count=len(session.events),
        state=dict(session.state),
    )


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _memory_response(record: MemoryRecord) -> MemoryResponse:
    created_at = _parse_iso_datetime(record.created_at) or datetime.fromtimestamp(0, UTC)
    return MemoryResponse(
        id=record.id,
        user_id=record.user_id,
        category=record.category,
        content=record.content,
        created_at=created_at,
        expires_at=_parse_iso_datetime(record.expires_at),
        updated_at=_parse_iso_datetime(record.updated_at),
        source=record.source,
        origin_session_id=record.origin_session_id,
        score=record.score,
    )


def _job_response(record: JobRecord) -> JobResponse:
    created_at = _parse_iso_datetime(record.created_at) or datetime.fromtimestamp(0, UTC)
    return JobResponse(
        id=record.id,
        kind=record.kind,
        state=record.state,
        progress=record.progress,
        error=record.error,
        params=record.params,
        result=record.result,
        user_id=record.user_id,
        created_at=created_at,
        finished_at=_parse_iso_datetime(record.finished_at),
    )


def _document_response(document: IngestedDocument) -> KnowledgeDocumentResponse:
    return KnowledgeDocumentResponse(
        doc_id=document.doc_id,
        title=document.title,
        source_path=document.source_path,
        oss_key=document.oss_key,
        user_id=document.user_id,
        tags=document.tags,
        chunks=document.chunks,
        pages=document.pages,
        ingested_at=_parse_iso_datetime(document.ingested_at),
    )


def _paper_response(record: PaperRecord) -> PaperResponse:
    created_at = _parse_iso_datetime(record.created_at) or datetime.fromtimestamp(0, UTC)
    return PaperResponse(
        id=record.id,
        arxiv_id=record.arxiv_id,
        doi=record.doi,
        title=record.title,
        authors=record.authors or [],
        venue=record.venue,
        year=record.year,
        tags=record.tags or [],
        read_at=_parse_iso_datetime(record.read_at),
        rating=record.rating,
        oss_path=record.oss_path,
        user_id=record.user_id,
        created_at=created_at,
        updated_at=_parse_iso_datetime(record.updated_at),
    )


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    return str(value)


def _summarize(value: Any, *, limit: int = 700) -> str:
    text = json.dumps(_jsonable(value), ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _citations_from_text(text: str) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for match in _CITATION_RE.finditer(text):
        page = match.group("page")
        section = match.group("section")
        citations.append(
            {
                "paper_id": match.group("paper_id").strip(),
                "page": int(page) if page else None,
                "section": section.strip() if section else None,
                "oss_key": None,
            }
        )
    return citations


def _part_is_thinking(part: Any) -> bool:
    if bool(getattr(part, "thought", False)):
        return True
    text = getattr(part, "text", None)
    if not text:
        return False
    return str(text).lstrip().startswith(_THOUGHT_PREFIXES)


def _part_text(part: Any) -> str:
    text = getattr(part, "text", None)
    return str(text) if text else ""


def _llm_error_payload(error: Exception) -> dict[str, Any]:
    code, message, retryable = classify_llm_error(error)
    return {
        "code": code,
        "message": message,
        "retryable": retryable,
    }


def _message_with_memory_context(
    *,
    memory_service: ResearchMemoryService,
    user_id: str,
    message: str,
) -> str:
    try:
        records = memory_service.search_records(query=message, user_id=user_id, top_k=5)
    except Exception:
        return message
    if not records:
        return message
    bullets = "\n".join(
        f"- {record.category}: {record.content}" for record in records if record.content
    )
    if not bullets:
        return message
    return (
        "以下是该用户的长期记忆，只能用于个性化、偏好和任务上下文，不能作为论文事实来源：\n"
        f"{bullets}\n\n"
        f"当前用户消息：{message}"
    )


async def _chat_event_stream(
    *,
    runtime: _ApiRuntime,
    user_id: str,
    session_id: str,
    message: str,
) -> AsyncIterator[str]:
    invocation_id = _new_uuid7()
    full_text_parts: list[str] = []
    emitted_citations: set[tuple[str, str]] = set()
    message_for_agent = _message_with_memory_context(
        memory_service=runtime.memory_service,
        user_id=user_id,
        message=message,
    )
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=message_for_agent)],
    )
    yield _sse("thinking", {"text": "agent_started", "invocation_id": invocation_id})
    try:
        async with asyncio.timeout(_CHAT_TIMEOUT_SECONDS):
            async with aclosing(
                runtime.runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=new_message,
                    invocation_id=invocation_id,
                )
            ) as events:
                async for event in events:
                    for function_call in event.get_function_calls():
                        yield _sse(
                            "tool_call",
                            {
                                "tool": getattr(function_call, "name", "unknown"),
                                "args": _jsonable(getattr(function_call, "args", {})),
                            },
                        )
                    for function_response in event.get_function_responses():
                        yield _sse(
                            "tool_result",
                            {
                                "tool": getattr(function_response, "name", "unknown"),
                                "result_summary": _summarize(
                                    getattr(function_response, "response", None)
                                ),
                            },
                        )

                    final_parts: list[str] = []
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            text = _part_text(part)
                            if text:
                                if _part_is_thinking(part):
                                    yield _sse("thinking", {"text": text})
                                else:
                                    final_parts.append(text)
                    if not final_parts:
                        continue
                    text_delta = "".join(final_parts)
                    if text_delta:
                        full_text_parts.append(text_delta)
                        yield _sse("token", {"delta": text_delta})
                        for citation in _citations_from_text(text_delta):
                            page = citation.get("page")
                            section = citation.get("section")
                            location = f"p:{page}" if page is not None else f"s:{section}"
                            key = (str(citation["paper_id"]), location)
                            if key not in emitted_citations:
                                emitted_citations.add(key)
                                yield _sse("citation", citation)

                    if event.is_final_response():
                        full_text = "".join(full_text_parts)
                        citations = _citations_from_text(full_text)
                        yield _sse(
                            "final",
                            {
                                "message_id": event.id or invocation_id,
                                "full_text": full_text,
                                "citations": citations,
                            },
                        )
                        return
        full_text = "".join(full_text_parts)
        yield _sse(
            "final",
            {
                "message_id": invocation_id,
                "full_text": full_text,
                "citations": _citations_from_text(full_text),
            },
        )
    except TimeoutError:
        yield _sse(
            "error",
            {
                "code": "TIMEOUT",
                "message": f"chat exceeded {_CHAT_TIMEOUT_SECONDS:.0f}s",
                "retryable": True,
            },
        )
    except Exception as exc:
        logger.bind(session_id=session_id, event="chat_error").exception("chat failed")
        error_payload = _llm_error_payload(exc)
        yield _sse(
            "error",
            error_payload,
        )


def _cache_path_for_oss_key(settings: Settings, key: str) -> Path:
    digest = uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:16]
    key_path = Path(key)
    suffix = key_path.suffix.lower()
    if not suffix:
        msg = f"OSS key must include a supported file extension: {key}"
        raise UnsupportedFormatError(msg)
    name = key_path.name or f"{digest}{suffix}"
    return settings.oss_cache_dir / digest / name


def _build_ingest_handler(
    *,
    settings: Settings,
    memory_service: ResearchMemoryService,
) -> Callable[[JobContext], Awaitable[dict[str, Any] | None]]:
    async def handle_ingest(context: JobContext) -> dict[str, Any]:
        oss_keys = [str(item) for item in context.params.get("oss_keys", [])]
        owner_user_id = str(context.params.get("owner_user_id") or context.user_id)
        tags = [str(item) for item in context.params.get("tags", []) if str(item).strip()]
        paper_id = context.params.get("paper_id")
        title = context.params.get("title")
        if not oss_keys:
            msg = "oss_keys must not be empty"
            raise ValueError(msg)
        if (paper_id or title) and len(oss_keys) != 1:
            msg = "paper_id/title overrides are only valid for one OSS key"
            raise ValueError(msg)

        oss_client = OssClient.from_settings(settings)
        kb_service = KnowledgeBaseService.from_settings(settings)
        paper_repo = PaperRepository.from_settings(settings)
        documents: list[dict[str, object]] = []
        total = len(oss_keys)
        for index, oss_key in enumerate(oss_keys, start=1):
            base_progress = (index - 1) / total * 95.0
            await context.progress(base_progress, f"downloading {oss_key}")
            local_path = _cache_path_for_oss_key(settings, oss_key)
            await asyncio.to_thread(oss_client.get_file, oss_key, local_path)

            await context.progress(base_progress + 20.0 / total, f"ingesting {oss_key}")
            document = await asyncio.to_thread(
                kb_service.ingest_document,
                local_path,
                paper_id=str(paper_id) if paper_id else None,
                title=str(title) if title else None,
                oss_key=oss_key,
                user_id=owner_user_id,
                tags=tags,
            )
            paper_repo.upsert_ingested_document(document)
            documents.append(document.to_payload())
            await context.progress(index / total * 95.0, f"ingested {document.doc_id}")

        if owner_user_id:
            memory_service.add_record(
                user_id=owner_user_id,
                category="recent_tasks",
                content=(
                    f"Knowledge ingest job {context.job_id} completed: "
                    f"{len(documents)} document(s), tags={tags}."
                ),
                source="job",
            )
        return {"documents": documents}

    return handle_ingest


async def _archive_idle_sessions(
    *,
    runtime: _ApiRuntime,
    settings: Settings,
) -> None:
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.memory_idle_archive_seconds)
    sessions = await runtime.session_service.list_sessions(app_name=APP_NAME)
    for session_stub in sessions.sessions:
        if session_stub.last_update_time > cutoff.timestamp():
            continue
        if runtime.memory_service.has_session_archive(session_stub.id):
            continue
        session = await runtime.session_service.get_session(
            app_name=APP_NAME,
            user_id=session_stub.user_id,
            session_id=session_stub.id,
        )
        if session is not None:
            await runtime.memory_service.add_session_to_memory(cast(Session, session))


async def _idle_archive_loop(
    *,
    runtime: _ApiRuntime,
    settings: Settings,
) -> None:
    while True:
        await asyncio.sleep(settings.memory_idle_scan_seconds)
        try:
            await _archive_idle_sessions(runtime=runtime, settings=settings)
        except Exception:
            logger.bind(event="memory_idle_archive_error").exception("idle memory archive failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _ensure_runtime_dirs(settings)
    _configure_logging()
    runtime = _get_runtime(settings)
    job_runner = JobRunner(settings.jobs_db_path)
    job_runner.register_handler(
        "ingest",
        _build_ingest_handler(settings=settings, memory_service=runtime.memory_service),
    )
    register_task_handlers(
        job_runner,
        settings=settings,
        memory_service=runtime.memory_service,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        _ensure_runtime_dirs(settings)
        await job_runner.start()
        archive_task = asyncio.create_task(
            _idle_archive_loop(runtime=runtime, settings=settings),
            name="rm-memory-idle-archive",
        )
        try:
            yield
        finally:
            archive_task.cancel()
            await asyncio.gather(archive_task, return_exceptions=True)
            await job_runner.close()
            closed_runtime = _runtime_by_session_uri.pop(settings.adk_session_db_url, None)
            if closed_runtime is not None:
                await closed_runtime.close()

    app = get_fast_api_app(
        agents_dir="src",
        session_service_uri=settings.adk_session_db_url,
        web=False,
        allow_origins=[
            "http://127.0.0.1",
            "http://127.0.0.1:8000",
            "http://localhost",
            "http://localhost:8000",
        ],
        host=settings.bind_host,
        port=settings.bind_port,
        lifespan=lifespan,
    )
    app.title = "ResearchMate"
    app.version = __version__
    app.description = "Local-first AI research assistant service."
    app.state.rm_settings = settings
    app.state.rm_job_runner = job_runner

    @app.middleware("http")
    async def request_context_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        trace_id = request.headers.get("X-Trace-Id") or _new_uuid7()
        token = _TRACE_ID.set(trace_id)
        try:
            with logger.contextualize(trace_id=trace_id):
                if _requires_token(request.url.path) and request.method != "OPTIONS":
                    expected = settings.research_agent_token.get_secret_value()
                    actual = request.headers.get("X-Internal-Token", "")
                    if not secrets.compare_digest(actual, expected):
                        return _error_response(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            code="UNAUTHORIZED",
                            message="missing or invalid X-Internal-Token",
                            trace_id=trace_id,
                        )
                started_at = time.perf_counter()
                try:
                    response = await call_next(request)
                except Exception as exc:
                    logger.bind(event="request_error").exception("unhandled request error")
                    response = _error_response(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        code="INTERNAL_ERROR",
                        message=str(exc),
                        trace_id=trace_id,
                    )
                latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
                response.headers["X-Trace-Id"] = trace_id
                logger.bind(
                    event="request",
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                ).info("request completed")
                return response
        finally:
            _TRACE_ID.reset(token)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        retryable = exc.status_code in {
            status.HTTP_429_TOO_MANY_REQUESTS,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            status.HTTP_504_GATEWAY_TIMEOUT,
        }
        return _error_response(
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message=str(exc.detail),
            retryable=retryable,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message=str(exc),
        )

    @app.get("/v1/livez", response_model=LivezResponse)
    async def livez() -> LivezResponse:
        return LivezResponse(status="ok", version=__version__)

    @app.get("/v1/readyz", response_model=ReadyzResponse)
    async def readyz() -> ReadyzResponse:
        return await _readyz_payload(settings)

    @app.get("/v1/healthz", response_model=HealthResponse)
    async def healthz(deep: bool = False) -> HealthResponse:
        ready = await _readyz_payload(settings)
        llm_status: LlmStatus | None = None
        if deep:
            llm_status = await _probe_llm(settings, force=True)
        elif _deep_health_cache.status is not None:
            llm_status = _deep_health_cache.status.model_copy(update={"cached": True})
        return HealthResponse(
            status=ready.status,
            version=ready.version,
            dependencies=ready.dependencies,
            runtime=ready.runtime,
            llm=llm_status,
        )

    @app.get("/v1/version", response_model=VersionResponse)
    async def version() -> VersionResponse:
        return VersionResponse(
            version=__version__,
            git_sha=_git_sha(),
            adk_version=adk_version,
            model=settings.researchmate_llm_model,
            runtime=_runtime_info(settings),
        )

    @app.post("/v1/sessions", response_model=SessionResponse)
    async def create_session(req: SessionCreateRequest) -> SessionResponse:
        runtime = _get_runtime(settings)
        session = await runtime.session_service.create_session(
            app_name=APP_NAME,
            user_id=req.user_id,
            state=req.state,
            session_id=req.session_id,
        )
        return _session_response(session)

    @app.get("/v1/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(session_id: str) -> SessionResponse:
        runtime = _get_runtime(settings)
        session = await _find_session(runtime, session_id)
        return _session_response(session)

    @app.delete("/v1/sessions/{session_id}", response_model=SessionDeleteResponse)
    async def delete_session(session_id: str) -> SessionDeleteResponse:
        session = await _find_session(runtime, session_id)
        await runtime.memory_service.add_session_to_memory(session)
        await runtime.session_service.delete_session(APP_NAME, session.user_id, session_id)
        return SessionDeleteResponse(session_id=session_id, deleted=True)

    @app.post("/v1/memory", response_model=MemoryResponse)
    async def create_memory(req: MemoryCreateRequest) -> MemoryResponse:
        record = runtime.memory_service.add_record(
            user_id=req.user_id,
            category=req.category,
            content=req.content,
            expires_at=req.expires_at.isoformat() if req.expires_at else None,
            source="api",
        )
        return _memory_response(record)

    @app.get("/v1/memory", response_model=MemoryListResponse)
    async def list_memory(
        user_id: str,
        category: str | None = None,
        include_expired: bool = False,
        limit: int = 100,
    ) -> MemoryListResponse:
        records = runtime.memory_service.list_records(
            user_id=user_id,
            category=category,
            include_expired=include_expired,
            limit=limit,
        )
        items = [_memory_response(record) for record in records]
        return MemoryListResponse(items=items, count=len(items))

    @app.patch("/v1/memory/{memory_id}", response_model=MemoryResponse)
    async def update_memory(memory_id: str, req: MemoryUpdateRequest) -> MemoryResponse:
        try:
            record = runtime.memory_service.update_record(
                memory_id,
                content=req.content,
                category=req.category,
                expires_at=req.expires_at.isoformat() if req.expires_at else None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return _memory_response(record)

    @app.delete("/v1/memory/{memory_id}", response_model=MemoryDeleteResponse)
    async def delete_memory(memory_id: str) -> MemoryDeleteResponse:
        deleted = runtime.memory_service.delete_record(memory_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
        return MemoryDeleteResponse(memory_id=memory_id, deleted=True)

    @app.post("/v1/memory/archive", response_model=MemoryArchiveResponse)
    async def archive_memory(req: MemoryArchiveRequest) -> MemoryArchiveResponse:
        session = await _find_session(runtime, req.session_id)
        archived_count = await runtime.memory_service.archive_session(session)
        return MemoryArchiveResponse(session_id=req.session_id, archived_count=archived_count)

    @app.post("/v1/knowledge/ingest", response_model=JobSubmitResponse)
    async def ingest_knowledge(req: KnowledgeIngestRequest) -> JobSubmitResponse:
        job_id = await job_runner.submit(
            "ingest",
            params=req.model_dump(mode="json"),
            user_id=req.owner_user_id,
        )
        return JobSubmitResponse(job_id=job_id)

    @app.get("/v1/knowledge/jobs/{job_id}", response_model=JobResponse)
    async def get_knowledge_job(job_id: str) -> JobResponse:
        record = await job_runner.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return _job_response(record)

    @app.post("/v1/knowledge/jobs/{job_id}/cancel", response_model=JobResponse)
    async def cancel_knowledge_job(job_id: str) -> JobResponse:
        cancelled = await job_runner.cancel(job_id)
        if not cancelled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found or already finished",
            )
        record = await job_runner.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return _job_response(record)

    @app.get("/v1/knowledge/jobs/{job_id}/events")
    async def stream_knowledge_job(job_id: str) -> StreamingResponse:
        if await job_runner.get_job(job_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

        async def event_stream() -> AsyncIterator[str]:
            async for event in job_runner.subscribe(job_id):
                yield _sse(event.event, event.data)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/knowledge/documents", response_model=KnowledgeDocumentListResponse)
    async def list_knowledge_documents(
        user_id: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> KnowledgeDocumentListResponse:
        service = KnowledgeBaseService.from_settings(settings)
        documents = service.list_documents(
            user_id=user_id,
            tag=tag,
            limit=limit,
            offset=offset,
        )
        items = [_document_response(document) for document in documents]
        return KnowledgeDocumentListResponse(items=items, count=len(items))

    @app.delete(
        "/v1/knowledge/documents/{doc_id}",
        response_model=KnowledgeDocumentDeleteResponse,
    )
    async def delete_knowledge_document(doc_id: str) -> KnowledgeDocumentDeleteResponse:
        service = KnowledgeBaseService.from_settings(settings)
        deleted = service.delete_document(doc_id)
        if deleted == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return KnowledgeDocumentDeleteResponse(doc_id=doc_id, deleted_chunks=deleted)

    @app.get("/v1/papers", response_model=PaperListResponse)
    async def list_papers(
        user_id: str | None = None,
        tag: str | None = None,
        year: int | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> PaperListResponse:
        repo = PaperRepository.from_settings(settings)
        records = repo.list_papers(
            user_id=user_id,
            tag=tag,
            year=year,
            q=q,
            limit=limit,
            offset=offset,
        )
        items = [_paper_response(record) for record in records]
        return PaperListResponse(items=items, count=len(items))

    @app.get("/v1/papers/{paper_id}", response_model=PaperResponse)
    async def get_paper(paper_id: str) -> PaperResponse:
        repo = PaperRepository.from_settings(settings)
        record = repo.get_paper(paper_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")
        return _paper_response(record)

    @app.patch("/v1/papers/{paper_id}", response_model=PaperResponse)
    async def update_paper(paper_id: str, req: PaperUpdateRequest) -> PaperResponse:
        repo = PaperRepository.from_settings(settings)
        try:
            record = repo.update_paper(
                paper_id,
                tags=req.tags,
                read_at=req.read_at.isoformat() if req.read_at else None,
                rating=req.rating,
            )
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return _paper_response(record)

    @app.get("/v1/tasks/kinds", response_model=TaskKindsResponse)
    async def list_task_kinds() -> TaskKindsResponse:
        return TaskKindsResponse(items=task_kind_schema_payload())

    @app.post("/v1/tasks/run", response_model=TaskSubmitResponse)
    async def run_task(req: TaskRunRequest) -> TaskSubmitResponse:
        normalized_kind = normalize_task_kind(req.kind)
        try:
            params = validate_task_params(normalized_kind, req.params)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        task_id = await job_runner.submit(normalized_kind, params=params, user_id=req.user_id)
        return TaskSubmitResponse(task_id=task_id)

    @app.get("/v1/tasks/{task_id}", response_model=JobResponse)
    async def get_task(task_id: str) -> JobResponse:
        record = await job_runner.get_job(task_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        return _job_response(record)

    @app.post("/v1/tasks/{task_id}/cancel", response_model=JobResponse)
    async def cancel_task(task_id: str) -> JobResponse:
        cancelled = await job_runner.cancel(task_id)
        if not cancelled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found or already finished",
            )
        record = await job_runner.get_job(task_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        return _job_response(record)

    @app.get("/v1/tasks/{task_id}/events")
    async def stream_task(task_id: str) -> StreamingResponse:
        if await job_runner.get_job(task_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

        async def event_stream() -> AsyncIterator[str]:
            async for event in job_runner.subscribe(task_id):
                yield _sse(event.event, event.data)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/chat/{session_id}")
    async def chat(session_id: str, req: ChatRequest) -> StreamingResponse:
        session = await _find_session(runtime, session_id)
        stream = _chat_event_stream(
            runtime=runtime,
            user_id=session.user_id,
            session_id=session_id,
            message=req.message,
        )
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
