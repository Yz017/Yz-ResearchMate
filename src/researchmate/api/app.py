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
from datetime import UTC, datetime
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
from researchmate.api.schemas import (
    ChatRequest,
    DependencyStatus,
    ErrorResponse,
    HealthResponse,
    LivezResponse,
    LlmStatus,
    ReadyzResponse,
    SessionCreateRequest,
    SessionDeleteResponse,
    SessionResponse,
    VersionResponse,
)
from researchmate.config import Settings, get_settings

APP_NAME = "researchmate"
_CHAT_TIMEOUT_SECONDS = 120.0
_DEEP_HEALTH_TTL_SECONDS = 300.0
_CITATION_RE = re.compile(r"\[source:\s*([^,\]]+),\s*p\.?(\d+)\]", re.IGNORECASE)
_TRACE_ID: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


@dataclass(slots=True)
class _DeepHealthCache:
    expires_at: float = 0.0
    status: LlmStatus | None = None


class _ApiRuntime:
    def __init__(self, settings: Settings) -> None:
        self.session_service = DatabaseSessionService(settings.adk_session_db_url)
        self.runner = Runner(
            app_name=APP_NAME,
            agent=root_agent,
            session_service=self.session_service,
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


async def _readyz_payload(settings: Settings) -> ReadyzResponse:
    dependencies = {
        "config": DependencyStatus(ok=True, detail="loaded"),
        "chroma": _check_chroma_dir(settings),
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
            try:
                litellm = importlib.import_module("litellm")
                await asyncio.wait_for(
                    litellm.acompletion(
                        model=settings.researchmate_llm_model,
                        messages=[{"role": "user", "content": "ping"}],
                        max_tokens=1,
                    ),
                    timeout=10.0,
                )
                status_payload = LlmStatus(
                    ok=True,
                    cached=False,
                    checked_at=checked_at,
                    detail="ok",
                )
            except Exception as exc:
                status_payload = LlmStatus(
                    ok=False,
                    cached=False,
                    checked_at=checked_at,
                    detail=f"{type(exc).__name__}: {exc}",
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
        citations.append(
            {
                "paper_id": match.group(1).strip(),
                "page": int(match.group(2)),
                "oss_key": None,
            }
        )
    return citations


async def _chat_event_stream(
    *,
    runtime: _ApiRuntime,
    user_id: str,
    session_id: str,
    message: str,
) -> AsyncIterator[str]:
    invocation_id = _new_uuid7()
    full_text_parts: list[str] = []
    emitted_citations: set[tuple[str, int]] = set()
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=message)],
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

                    text_parts: list[str] = []
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            text = getattr(part, "text", None)
                            if text:
                                text_parts.append(str(text))
                    if not text_parts:
                        continue
                    text_delta = "".join(text_parts)
                    if text_delta:
                        full_text_parts.append(text_delta)
                        yield _sse("token", {"delta": text_delta})
                        for citation in _citations_from_text(text_delta):
                            key = (str(citation["paper_id"]), int(citation["page"]))
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
        yield _sse(
            "error",
            {
                "code": "CHAT_FAILED",
                "message": f"{type(exc).__name__}: {exc}",
                "retryable": False,
            },
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _ensure_runtime_dirs(settings)
    _configure_logging()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        _ensure_runtime_dirs(settings)
        try:
            yield
        finally:
            runtime = _runtime_by_session_uri.pop(settings.adk_session_db_url, None)
            if runtime is not None:
                await runtime.close()

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
        runtime = _get_runtime(settings)
        session = await _find_session(runtime, session_id)
        await runtime.session_service.delete_session(APP_NAME, session.user_id, session_id)
        return SessionDeleteResponse(session_id=session_id, deleted=True)

    @app.post("/v1/chat/{session_id}")
    async def chat(session_id: str, req: ChatRequest) -> StreamingResponse:
        runtime = _get_runtime(settings)
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
